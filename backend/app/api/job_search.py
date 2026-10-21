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
    CoverageOut,
    JobSearchIn,
    JobSearchPageOut,
    JobSearchWebOut,
    JobSearchResultOut,
    JobSearchRunOut,
)
from app.services.discovery import manual_extraction, web_search
from app.services.discovery.base import RawJobPosting
from app.repositories.profile_repository import get_current_profile
from app.services.discovery.normalization import html_to_text, parse_salary
from app.services.discovery.pipeline import ingest_manual_posting
from app.services.jobcache.keys import loose_keys
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


def _run_out(db: Session, found: int, skipped: int, outcome: web_search.SearchOutcome | None = None) -> JobSearchRunOut:
    out = JobSearchRunOut(
        found=found,
        skipped=skipped,
        results=[JobSearchResultOut.model_validate(r) for r in _new_results(db)],
    )
    if outcome is not None:
        out.coverage = CoverageOut(**outcome.coverage) if outcome.coverage else None
        out.more_available = outcome.more_available
        out.more_capped = outcome.more_capped
    return out


def _save_item(db: Session, item: dict, payload: JobSearchIn) -> JobSearchResult:
    """
    The result row for a found job. A job already on the list is reused, and one set aside by an earlier search comes back
    with its resume score intact, so a job is never saved twice and never scored twice.
    """
    from app.services.jobcache.text import effective_work_type

    item = {**item, "work_type": effective_work_type(item.get("work_type"), item.get("location"))}  # on site unless the employer says otherwise
    row = (
        db.query(JobSearchResult)
        .filter(JobSearchResult.url_key == item["url_key"], JobSearchResult.status.in_(("new", "stale")))
        .order_by(JobSearchResult.status.asc())  # "new" before "stale"
        .first()
    )
    if row is None:
        row = JobSearchResult(**item, status="new", criteria=payload.model_dump())
        db.add(row)
        return row
    row.fit_score = item.get("fit_score")
    row.fit_note = item.get("fit_note")
    # What the job says now (its place list, pay, date) replaces what an earlier search saved, so a page never shows stale details.
    for key in ("title", "company", "location", "work_type", "salary_text", "posted_at"):
        if item.get(key) is not None:
            setattr(row, key, item[key])
    if row.status == "stale":
        row.status = "new"
        row.criteria = payload.model_dump()
    return row


@router.get("/places")
def suggest_places(q: str = "") -> list[dict[str, str]]:
    """City suggestions while typing in the place box ("Bost" offers "Boston, MA")."""
    from app.services.jobcache import places
    from app.services.jobcache.store import JobCache

    try:
        known = JobCache().locations_sample()
    except Exception:  # the saved lists are a bonus: the built-in cities still work without them
        known = []
    return places.suggest(q[:60], known)


@router.get("/suggest")
def suggest_words(kind: str = "title", q: str = "") -> list[dict[str, str]]:
    """Suggestions while typing a job title or a keyword."""
    from app.services.jobcache import suggest
    from app.services.jobcache.store import JobCache

    q = q[:60]
    if kind == "keyword":
        return suggest.keywords(q)
    try:
        rows = JobCache().titles_sample(q)
    except Exception:  # the saved lists are a bonus: typing still works without them
        rows = []
    return suggest.titles(q, rows)


@router.get("/results", response_model=JobSearchRunOut)
def list_results(db: Session = Depends(get_db)) -> JobSearchRunOut:
    return _run_out(db, 0, 0)


@router.post("/run", response_model=JobSearchRunOut)
async def run_search(payload: JobSearchIn, db: Session = Depends(get_db)) -> JobSearchRunOut:
    # Everything already saved or shown is passed in, so the saved employer lists return the NEXT best matches each time
    # (this is what makes "Show more results" work) and never fill the list with postings you have already seen.
    known: set[str] = set()
    for (url,) in db.query(Job.canonical_application_url).all():
        known |= loose_keys(url)
    # Only jobs you added or hid are left out of a search. Jobs an earlier search showed can come up again.
    seen = db.query(JobSearchResult.url).filter(JobSearchResult.status.in_(("added", "removed") if not payload.more else ("added", "removed", "new")))
    for (url,) in seen.all():
        known |= loose_keys(url)
    try:
        outcome = await web_search.search_jobs_full(payload, known_keys=known, cache_only=payload.more or payload.web == "saved")
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

    if not payload.more:
        # A new search starts a new list. The old one is set aside (not deleted), so its resume scores are not lost.
        db.query(JobSearchResult).filter(JobSearchResult.status == "new").update({"status": "stale"}, synchronize_session=False)
    found = 0
    skipped = outcome.skipped  # postings that were clearly closed when the link was opened
    for item in outcome.items:
        if loose_keys(item["url"]) & known:
            skipped += 1
            continue
        known |= loose_keys(item["url"])
        _save_item(db, item, payload)
        found += 1
    db.commit()
    return _run_out(db, found, skipped, outcome)


@router.post("/web", response_model=JobSearchWebOut)
async def search_web(payload: JobSearchIn, db: Session = Depends(get_db)) -> JobSearchWebOut:
    """
    The web search on its own, run after the saved-list results are already showing. What it finds is ranked into the same list
    the pages are cut from, so each job lands on the page its match earns. Nothing is saved here; the jobs are saved when their
    page is opened. If the web search is unavailable the answer is simply "nothing added".
    """
    from app.services.jobcache import service as cache_service

    known: set[str] = set()
    for (url,) in db.query(Job.canonical_application_url).all():
        known |= loose_keys(url)
    for (url,) in db.query(JobSearchResult.url).filter(JobSearchResult.status.in_(("removed", "added"))).all():
        known |= loose_keys(url)
    if cache_service.web_searched_recently(payload):  # the identical search ran within the hour: its finds are already in the saved lists
        return JobSearchWebOut(added=0, total=len(await cache_service.ranked_items(payload)))
    try:
        outcome = await web_search.search_jobs_full(payload, known_keys=known, web_only=True)
        cache_service.note_web_searched(payload)
    except Exception:  # the web search is a bonus on top of the saved lists: any failure just means nothing is added
        total = len(await cache_service.ranked_items(payload))
        return JobSearchWebOut(added=0, total=total)
    fresh = [i for i in outcome.items if not (loose_keys(i["url"]) & known)]
    try:  # the employers behind what the web search found join the saved lists, so later searches find their other jobs without the web
        await cache_service.adopt_employers_from_web([(i["url"], i.get("company")) for i in outcome.items])
    except Exception:
        pass
    added, total = await cache_service.add_to_ranked(payload, fresh)
    return JobSearchWebOut(added=added, total=total)


@router.post("/page", response_model=JobSearchPageOut)
async def search_page(payload: JobSearchIn, db: Session = Depends(get_db)) -> JobSearchPageOut:
    """
    One page of the saved-list matches (any page, quickly). The jobs shown are saved as results too, so adding, hiding and
    scoring work on them like any other result. Jobs already in Jobs or removed are left out.
    """
    page = payload.page or 0
    known: set[str] = set()
    for (url,) in db.query(Job.canonical_application_url).all():
        known |= loose_keys(url)
    for (url,) in db.query(JobSearchResult.url).filter(JobSearchResult.status.in_(("removed", "added"))).all():
        known |= loose_keys(url)
    try:
        scores = {}
        if payload.sort == "resume":
            scores = {k: v for k, v in db.query(JobSearchResult.url_key, JobSearchResult.match_score).filter(JobSearchResult.match_score.isnot(None)).all()}
        items, total = await web_search.search_page(
            payload, known, max(page - 1, 0) * payload.count, sort=payload.sort, resume_scores=scores, count_only=(payload.page == 0)
        )
    except (httpx.HTTPError, LLMError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The search service didn't answer. Try again in a minute.") from exc
    rows: list[JobSearchResult] = []
    for item in items:
        rows.append(_save_item(db, item, payload))
    db.commit()
    for row in rows:
        db.refresh(row)
    return JobSearchPageOut(total=total, results=[JobSearchResultOut.model_validate(r) for r in rows])


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


# A real posting runs to paragraphs. Anything much shorter is a stub or an error page, not enough to judge a fit.
_MIN_SCORE_CHARS = 300


async def _read_posting_for_score(db: Session, row: JobSearchResult) -> tuple[str, str | None]:
    """
    Reads the posting page for scoring. Returns (requirements text, problem). Problem is None when the
    text is a real posting, "closed" when the page is gone or says the job is closed, "unreadable" when
    the site blocked the read or gave back too little to judge.
    """
    try:
        page = await manual_extraction.fetch_page(row.url)
    except manual_extraction.ManualExtractionError as exc:
        cause = exc.__cause__
        if isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code in (404, 410):
            return "", "closed"
        return "", "unreadable"
    except httpx.HTTPError:
        return "", "unreadable"
    if web_search.looks_closed(row.url, row.url, 200, page.body_text):
        return "", "closed"
    try:
        posting = await manual_extraction.extract_job_posting(
            db,
            url=row.url,
            json_ld_blocks=page.json_ld_blocks,
            body_text=page.body_text,
            page_title=page.title,
        )
    except (manual_extraction.ManualExtractionError, LLMError, httpx.HTTPError):
        return "", "unreadable"
    text = html_to_text(posting.description_html)[:12000] if posting.description_html else ""
    if web_search.looks_closed(row.url, row.url, 200, text):
        return "", "closed"
    if len(text.strip()) < _MIN_SCORE_CHARS:
        return "", "unreadable"
    return text, None


@router.post("/results/{result_id}/score", response_model=JobSearchResultOut)
async def score_result(result_id: int, db: Session = Depends(get_db)) -> JobSearchResultOut:
    """
    Match score for one result, only when the person asks. The posting page is read first so the score
    is based on the real requirements. If the page is closed, blocked or too thin to judge, nothing is
    scored: a fit judged from a one-line summary would look more certain than it is. Costs one or two AI calls
    and adds nothing to the jobs list.
    """
    row = _get_new(db, result_id)
    if get_current_profile(db) is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Upload your resume on the Profile page first.")
    if not row.description or row.match_from_page is not True:
        text, problem = await _read_posting_for_score(db, row)
        if problem is not None:
            if row.match_from_page is False:
                # An older score that came from the short summary only: take it back rather than leave it standing.
                row.match_score = None
                row.match_summary = None
                row.match_gaps = None
                db.commit()
            if problem == "closed":
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail="This posting looks closed or removed, so it can't be scored. Open the posting to check, then remove it if it's gone.",
                )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The posting page couldn't be read, so there isn't enough detail to score it fairly. Open the posting to check it yourself.",
            )
        row.description = text
        row.match_from_page = True
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
    if row.match_score is not None and row.match_from_page is not False and not job.evaluations:
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
