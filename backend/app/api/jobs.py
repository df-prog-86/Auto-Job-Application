"""Job listing (spec §75), plus manual job intake: the user does their own
job search (LinkedIn, Indeed, a company site, wherever) and hands us one
posting at a time, either by pasting its URL or via the browser extension
capturing the page it's already looking at. See
app/services/discovery/manual_extraction.py for why this sidesteps the
compliance concerns that govern the automated per-employer discovery loop."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_extension_auth
from app.models.documents import GeneratedDocument
from app.models.jobs import Job
from app.repositories.profile_repository import get_current_profile
from app.schemas.discovery import (
    CaptureJobIn,
    GeneratedDocumentOut,
    JobDetailOut,
    FollowUpIn,
    FollowUpOut,
    JobOut,
    ManualJobIn,
    MarkAppliedIn,
    TailorResumeOut,
)
from app.services.discovery import manual_extraction
from app.services.discovery.pipeline import ingest_manual_posting
from app.services.followup.draft import FollowUpDraftError, draft_follow_up
from app.services.qualification.pipeline import qualify_job
from app.services.resume.service import (
    MasterMissingError,
    is_safe_document_path,
    remove_job_documents,
    tailor_resume,
    use_original_resume,
)

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


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

    job, created = ingest_manual_posting(db, posting, source_label="manual_url")
    # Qualification is not run here -- it costs an LLM call, so it only runs
    # when the candidate asks for it via POST /jobs/{id}/qualify (the
    # "Score match" button on the Jobs page), never automatically.
    out = JobOut.model_validate(job)
    out.already_existed = not created
    return out


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

    job, created = ingest_manual_posting(db, posting, source_label="extension_capture")
    # Same as above: no automatic scoring, so capturing a job never calls
    # the LLM by itself either.
    out = JobOut.model_validate(job)
    out.already_existed = not created
    return out


@router.post("/{job_id}/qualify", response_model=JobOut)
async def requalify_job(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    """
    The only place qualification scoring runs -- one LLM call that directly
    compares the candidate's resume/profile against the job description
    (see services/qualification/pipeline.py), only when the candidate
    explicitly clicks "Score match" (first run) or "Re-score match" (e.g.
    after updating their profile) on the Jobs page. Scoring never runs
    automatically on add, so adding a job never costs an LLM call by
    itself.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    try:
        await qualify_job(db, job)
    except Exception as exc:  # scoring is best-effort; never a 500 for the button click
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Couldn't score this job: {exc}"
        ) from exc
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{job_id}/tailor", response_model=TailorResumeOut)
async def tailor_resume_for_job(job_id: int, db: Session = Depends(get_db)) -> TailorResumeOut:
    """
    Milestone 5: edits a copy of the candidate's master Word resume into a
    tailored resume (Word). Only allowed once the candidate has clicked
    "Proceed with Application" for this job -- same explicit gate as everything
    downstream.
    Nothing is submitted anywhere; this only writes files on this computer.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    if job.application_status != "proceeding":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Click 'Proceed with Application' on this job before creating a tailored resume.",
        )
    profile = get_current_profile(db)
    try:
        outcome = await tailor_resume(db, job, profile.name if profile else "Candidate")
    except MasterMissingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Couldn't create the tailored resume: {exc}"
        ) from exc
    return TailorResumeOut(
        documents=[GeneratedDocumentOut.model_validate(d) for d in outcome.documents],
        used_original_wording=outcome.used_original_wording,
        problems=outcome.problems,
        changelog=outcome.changelog,
    )


@router.post("/{job_id}/original-resume", response_model=list[GeneratedDocumentOut])
def original_resume_for_job(job_id: int, db: Session = Depends(get_db)) -> list[GeneratedDocumentOut]:
    """Apply with the saved master resume as it is, instead of tailoring it. Same gate as tailoring."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    if job.application_status != "proceeding":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Click 'Proceed with Application' on this job before choosing a resume.",
        )
    profile = get_current_profile(db)
    try:
        doc = use_original_resume(db, job, profile.name if profile else "Candidate")
    except MasterMissingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return [GeneratedDocumentOut.model_validate(doc)]


@router.get("/documents/{document_id}/download")
def download_document(document_id: int, db: Session = Depends(get_db)) -> FileResponse:
    doc = db.get(GeneratedDocument, document_id)
    if doc is None or not is_safe_document_path(doc.local_path) or not Path(doc.local_path).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return FileResponse(doc.local_path, filename=Path(doc.local_path).name)


@router.post("/{job_id}/unproceed", response_model=JobOut)
def undo_proceed(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    """Takes back "Proceed with Application" (e.g. clicked by mistake). Anything
    already generated for the job is kept; it just goes back to not started."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    job.application_status = "not_started"
    db.commit()
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{job_id}/follow-up-draft", response_model=FollowUpOut)
async def follow_up_draft(job_id: int, payload: FollowUpIn | None = None, db: Session = Depends(get_db)) -> FollowUpOut:
    """A short message the person can edit and send themselves. Nothing is sent or saved."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    kind = "after_interview" if payload and payload.kind == "after_interview" else "after_applying"
    try:
        draft = await draft_follow_up(db, job, kind)
    except FollowUpDraftError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return FollowUpOut(subject=draft.subject, body=draft.body)


@router.post("/{job_id}/applied", response_model=JobOut)
def mark_applied(job_id: int, payload: MarkAppliedIn | None = None, db: Session = Depends(get_db)) -> JobOut:
    """The candidate says they sent this application (optionally on an earlier day)."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    now = dt.datetime.now(dt.timezone.utc)
    day = payload.applied_on if payload and payload.applied_on else None
    if day is not None:
        if day > now.date():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That date is in the future.")
        job.applied_at = dt.datetime.combine(day, dt.time(12, 0), tzinfo=dt.timezone.utc)
    else:
        job.applied_at = now
    job.applied_via = "manual"
    db.commit()
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{job_id}/interviewing", response_model=JobOut)
def mark_interviewing(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    """The candidate moved to interviews. An interview means they applied, so that is recorded too."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    now = dt.datetime.now(dt.timezone.utc)
    job.interviewing_at = now
    if job.applied_at is None:
        job.applied_at = now
        job.applied_via = "manual"
    db.commit()
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{job_id}/not-interviewing", response_model=JobOut)
def mark_not_interviewing(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    job.interviewing_at = None
    db.commit()
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{job_id}/follow-up-done", response_model=JobOut)
def follow_up_done(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    """Clears the Home follow-up reminder for this job."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    job.followup_done_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{job_id}/unapplied", response_model=JobOut)
def mark_not_applied(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    """Takes back "Mark as applied" (or a submission the extension saw by mistake)."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    job.applied_at = None
    job.applied_via = None
    job.interviewing_at = None
    db.commit()
    db.refresh(job)
    return JobOut.model_validate(job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: int, db: Session = Depends(get_db)) -> None:
    """Removes a job, its score, and any tailored resume files made for it."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    remove_job_documents(db, job)
    db.delete(job)
    db.commit()


@router.post("/{job_id}/proceed", response_model=JobOut)
def proceed_with_application(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    """
    The explicit, candidate-initiated gate: qualification scoring (when the
    candidate asks for it) is purely informational, but nothing downstream
    of it -- tailoring, touching a real application -- ever starts on its
    own. This is what the "Proceed with Application" button on the Jobs
    page calls -- right now it only records the decision, since
    tailoring/application execution (Milestones 5-6) aren't built yet.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    job.application_status = "proceeding"
    db.commit()
    db.refresh(job)
    return JobOut.model_validate(job)
