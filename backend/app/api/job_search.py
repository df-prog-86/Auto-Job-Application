"""Job Search: look for postings across the web, then add the good ones to the jobs list (or remove them)."""

from __future__ import annotations

import datetime as dt
import html

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.job_search import JobSearchResult
from app.models.jobs import Job, JobEvaluation
from app.schemas.discovery import JobOut
from app.schemas.job_search import (
    AddResultOut,
    ClearOut,
    JobSearchIn,
    JobSearchResultOut,
    JobSearchRunOut,
)
from app.services.discovery import manual_extraction, web_search
from app.services.discovery.base import RawJobPosting
from app.repositories.profile_repository import get_current_profile
from app.services.discovery.normalization import html_to_text, parse_salary
from app.services.discovery.pipeline import ingest_manual_posting
from app.services.llm.exceptions import LLMError, LLMNotConfiguredError
from app.services.qualification.pipeline import QualificationError, score_against

router = APIRouter(prefix="/api/v1/job-search", tags=["job-search"])


def _new_results(db: Session) -> list[JobSearchResult]:
    rows = (
        db.query(JobSearchResult)
        .filter(JobSearchResult.status == "new")
        .order_by(JobSearchResult.id.desc())
        .all()
    )
    # A posting that is already on the Jobs page (added here or any other way) is not offered again.
    in_jobs = {web_search.url_key(u) for (u,) in db.query(Job.canonical_application_url).all()}
    return [r for r in rows if r.url_key not in in_jobs]


def _run_out(db: Session, found: int, skipped: int) -> JobSearchRunOut:
    return JobSearchRunOut(
        found=found,
        skipped=skipped,
        results=[JobSearchResultOut.model_validate(r) for r in _new_results(db)],
    )


@router.get("/results", response_model=JobSearchRunOut)
def list_results(db: Session = Depends(get_db)) -> JobSearchRunOut:
    return _run_out(db, 0, 0)


@router.post("/run", response_model=JobSearchRunOut)
async def run_search(payload: JobSearchIn, db: Session = Depends(get_db)) -> JobSearchRunOut:
    try:
        items, closed = await web_search.search_jobs(payload)
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job search needs the AI connection, which isn't set up yet. See the backend README.",
        ) from exc
    except (httpx.HTTPError, LLMError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The search service didn't answer. Try again in a minute.",
        ) from exc

    known = {web_search.url_key(u) for (u,) in db.query(Job.canonical_application_url).all()}
    known |= {k for (k,) in db.query(JobSearchResult.url_key).all()}  # shown, added or removed before
    found = 0
    skipped = closed  # postings that were clearly closed when the link was opened
    for item in items:
        if item["url_key"] in known:
            skipped += 1
            continue
        known.add(item["url_key"])
        db.add(JobSearchResult(**item, status="new", criteria=payload.model_dump()))
        found += 1
    db.commit()
    return _run_out(db, found, skipped)


def _get_new(db: Session, result_id: int) -> JobSearchResult:
    row = db.get(JobSearchResult, result_id)
    if row is None or row.status != "new":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That result is no longer on the list.")
    return row


async def _read_posting(db: Session, row: JobSearchResult) -> RawJobPosting | None:
    """Reads the posting page and pulls out its requirements. None when the site will not let it be read."""
    try:
        page = await manual_extraction.fetch_page(row.url)
        return await manual_extraction.extract_job_posting(
            db,
            url=row.url,
            json_ld_blocks=page.json_ld_blocks,
            body_text=page.body_text,
            page_title=page.title,
        )
    except (manual_extraction.ManualExtractionError, LLMError, httpx.HTTPError):
        return None


@router.post("/results/{result_id}/score", response_model=JobSearchResultOut)
async def score_result(result_id: int, db: Session = Depends(get_db)) -> JobSearchResultOut:
    """
    Match score for one result, only when the person asks. The posting page is read first so the score
    is based on the real requirements; if the site blocks that, the short search summary is used and
    the result says so. Costs one or two AI calls and adds nothing to the jobs list.
    """
    row = _get_new(db, result_id)
    if get_current_profile(db) is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Upload your resume on the Profile page first.")
    if not row.description:
        posting = await _read_posting(db, row)
        if posting is not None and posting.description_html:
            row.description = html_to_text(posting.description_html)[:12000]
            row.match_from_page = True
        else:
            row.description = row.summary
            row.match_from_page = False
    if not row.description:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No requirements could be read for this posting, so it can't be scored. Open the posting to check it yourself.",
        )
    try:
        result = await score_against(db, title=row.title, company=row.company, description=row.description)
    except QualificationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    row.match_score = round(result.match_percentage / 100, 3)
    row.match_summary = result.summary
    row.match_gaps = list(result.gaps)
    db.commit()
    db.refresh(row)
    return JobSearchResultOut.model_validate(row)


@router.post("/results/{result_id}/add", response_model=AddResultOut)
async def add_result(result_id: int, db: Session = Depends(get_db)) -> AddResultOut:
    """
    Adds the posting to the jobs list. The posting page is read first (the same way as pasting a link);
    if the site won't let it be read, the search summary is used instead so the job is not lost.
    """
    row = _get_new(db, result_id)
    posting = await _read_posting(db, row)

    from_summary = posting is None
    if posting is None:
        posting = RawJobPosting(
            external_job_id=row.url_key,
            title=row.title,
            company=row.company,
            location=row.location,
            description_html=(
                f"<p>{html.escape(row.description or row.summary or '')}</p>" if (row.description or row.summary) else None
            ),
            application_url=row.url,
            salary_text=row.salary_text,
        )

    if posting.posted_at is None and row.posted_at:
        posting.posted_at = dt.datetime(row.posted_at.year, row.posted_at.month, row.posted_at.day, tzinfo=dt.timezone.utc)
    job, created = ingest_manual_posting(db, posting, source_label="web_search")
    # Keep the pay range the search showed, even when the page itself could not be read for it.
    pay_text = posting.salary_text or row.salary_text
    if pay_text:
        pay = dict(job.salary or {})
        if "min" not in pay and "max" not in pay:
            pay = {**parse_salary(pay_text), **pay}
        pay["text"] = pay_text
        job.salary = pay
    if job.posted_at is None and row.posted_at:
        job.posted_at = row.posted_at
    # A score asked for on this page goes with the job, so it is not asked for twice.
    if row.match_score is not None and not job.evaluations:
        db.add(
            JobEvaluation(
                job_id=job.id,
                overall_score=row.match_score,
                summary=row.match_summary or "",
                gaps=list(row.match_gaps or []),
                model_used="resume_job_match_v1",
                evaluation_version="2",
            )
        )
    row.status = "added"
    row.job_id = job.id
    db.commit()
    out = JobOut.model_validate(job)
    out.already_existed = not created
    return AddResultOut(job=out, from_summary=from_summary)


@router.post("/results/{result_id}/remove", response_model=JobSearchResultOut)
def remove_result(result_id: int, db: Session = Depends(get_db)) -> JobSearchResultOut:
    """Hides the result. It is kept, hidden, so the same posting is not offered again."""
    row = _get_new(db, result_id)
    row.status = "removed"
    db.commit()
    db.refresh(row)
    return JobSearchResultOut.model_validate(row)


@router.post("/clear", response_model=ClearOut)
def clear_results(db: Session = Depends(get_db)) -> ClearOut:
    rows = _new_results(db)
    for row in rows:
        row.status = "removed"
    db.commit()
    return ClearOut(cleared=len(rows))
