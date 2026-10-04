"""Job Search: look for postings across the web, then add the good ones to the jobs list (or remove them)."""

from __future__ import annotations

import html

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.job_search import JobSearchResult
from app.models.jobs import Job
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
from app.services.discovery.pipeline import ingest_manual_posting
from app.services.llm.exceptions import LLMError, LLMNotConfiguredError

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


@router.post("/results/{result_id}/add", response_model=AddResultOut)
async def add_result(result_id: int, db: Session = Depends(get_db)) -> AddResultOut:
    """
    Adds the posting to the jobs list. The posting page is read first (the same way as pasting a link);
    if the site won't let it be read, the search summary is used instead so the job is not lost.
    """
    row = _get_new(db, result_id)
    posting: RawJobPosting | None = None
    try:
        page = await manual_extraction.fetch_page(row.url)
        posting = await manual_extraction.extract_job_posting(
            db,
            url=row.url,
            json_ld_blocks=page.json_ld_blocks,
            body_text=page.body_text,
            page_title=page.title,
        )
    except (manual_extraction.ManualExtractionError, LLMError, httpx.HTTPError):
        posting = None

    from_summary = posting is None
    if posting is None:
        posting = RawJobPosting(
            external_job_id=row.url_key,
            title=row.title,
            company=row.company,
            location=row.location,
            description_html=f"<p>{html.escape(row.summary or '')}</p>" if row.summary else None,
            application_url=row.url,
            salary_text=row.salary_text,
        )

    job, created = ingest_manual_posting(db, posting, source_label="web_search")
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
