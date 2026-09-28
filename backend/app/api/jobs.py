"""Job listing (spec §75), plus manual job intake: the user does their own
job search (LinkedIn, Indeed, a company site, wherever) and hands us one
posting at a time, either by pasting its URL or via the browser extension
capturing the page it's already looking at. See
app/services/discovery/manual_extraction.py for why this sidesteps the
compliance concerns that govern the automated per-employer discovery loop."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_extension_auth
from app.models.jobs import Job
from app.schemas.discovery import CaptureJobIn, JobDetailOut, JobOut, ManualJobIn
from app.services.discovery import manual_extraction
from app.services.discovery.pipeline import ingest_manual_posting
from app.services.qualification.pipeline import qualify_job

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


async def _qualify_best_effort(db: Session, job: Job) -> None:
    """
    Qualification (spec §21-23) runs automatically on every newly-added job
    -- scoring is informational, costs one cheap LLM call at most, and
    doesn't touch anything else. It must never take down the "add a job"
    action it rides along with, so a failure here is swallowed: the job
    stays added, just without a score yet (evaluation stays None until a
    manual re-run via POST /jobs/{id}/qualify).
    """
    try:
        await qualify_job(db, job)
    except Exception:
        db.rollback()


@router.get("", response_model=list[JobOut])
def list_jobs(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[JobOut]:
    jobs = (
        db.query(Job)
        .order_by(Job.last_seen.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [JobOut.model_validate(j) for j in jobs]


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobDetailOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return JobDetailOut.model_validate(job)


@router.post("/manual", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def add_job_by_url(payload: ManualJobIn, db: Session = Depends(get_db)) -> JobOut:
    """Option 1: paste a job posting URL, the backend fetches that one page
    itself. Some sites (notably LinkedIn/Indeed) block automated fetches
    even for a single page -- when that happens the error message points
    the user at the extension capture endpoint below instead."""
    try:
        page = await manual_extraction.fetch_page(payload.url)
    except manual_extraction.ManualExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    try:
        posting = await manual_extraction.extract_job_posting(
            db,
            url=payload.url,
            json_ld_blocks=page.json_ld_blocks,
            body_text=page.body_text,
            page_title=page.title,
        )
    except manual_extraction.ManualExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    job = ingest_manual_posting(db, posting, source_label="manual_url")
    await _qualify_best_effort(db, job)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/capture", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def add_job_from_extension(
    payload: CaptureJobIn,
    db: Session = Depends(get_db),
    _pairing=Depends(require_extension_auth),
) -> JobOut:
    """Option 2: the browser extension already read the page the user is
    looking at, from their own logged-in session, and hands us its content
    directly -- no server-side fetch, so this works even on sites that block
    automated requests."""
    try:
        posting = await manual_extraction.extract_job_posting(
            db,
            url=payload.url,
            json_ld_blocks=payload.json_ld,
            body_text=payload.body_text,
            page_title=payload.page_title,
        )
    except manual_extraction.ManualExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    job = ingest_manual_posting(db, posting, source_label="extension_capture")
    await _qualify_best_effort(db, job)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{job_id}/qualify", response_model=JobOut)
async def requalify_job(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    """Manually re-run qualification -- useful after updating your profile
    or search preferences, since scoring is otherwise only run once, when
    the job is first added."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    await qualify_job(db, job)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{job_id}/proceed", response_model=JobOut)
def proceed_with_application(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    """
    The explicit, candidate-initiated gate: qualification scoring is
    automatic and purely informational, but nothing downstream of it
    (tailoring, touching a real application) ever starts on its own. This
    is what the "Proceed with Application" button on the Jobs page calls --
    right now it only records the decision, since tailoring/application
    execution (Milestones 5-6) aren't built yet.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    job.application_status = "proceeding"
    db.commit()
    db.refresh(job)
    return JobOut.model_validate(job)
