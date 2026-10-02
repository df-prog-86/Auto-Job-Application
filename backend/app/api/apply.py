"""
Endpoints the browser extension uses to fill an application page the user
has open (Milestone 6). Everything here is extension-token guarded. The
extension fills what it is sure about and reports the rest back as
questions for the Needs Attention page; it never submits anything.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_extension_auth
from app.models.candidate import CandidateAnswer
from app.models.jobs import Job
from app.models.questions import PendingQuestion
from app.repositories.profile_repository import get_current_profile
from app.schemas.apply import (
    ApplyContextIn,
    ApplyContextOut,
    ApplyJob,
    ApplyReportIn,
    ApplyResume,
    CandidateFacts,
)
from app.services.apply.questions import normalize_question, urls_match

router = APIRouter(prefix="/api/v1/apply", tags=["apply"], dependencies=[Depends(require_extension_auth)])

ELIGIBILITY_KEYS = (
    "work_authorization",
    "sponsorship_required",
    "security_clearance",
    "phone_country",
    # Voluntary self-identification: only present if the person chose an answer on their Profile.
    "eeo_gender",
    "eeo_race",
    "eeo_veteran",
)


def _apply_job(job: Job) -> ApplyJob:
    return ApplyJob(
        id=job.id,
        title=job.title,
        company=job.company,
        url=job.canonical_application_url,
        proceeding=job.application_status == "proceeding",
    )


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


@router.post("/context", response_model=ApplyContextOut)
def get_apply_context(payload: ApplyContextIn, db: Session = Depends(get_db)) -> ApplyContextOut:
    profile = get_current_profile(db)
    if profile is None:
        return ApplyContextOut(problem="Upload your resume on the Profile page first.")

    jobs = db.query(Job).order_by(Job.last_seen.desc()).all()
    job: Job | None = None
    if payload.job_id is not None:
        job = next((j for j in jobs if j.id == payload.job_id), None)
    if job is None:
        job = next((j for j in jobs if urls_match(payload.url, j.canonical_application_url)), None)

    if job is None:
        return ApplyContextOut(
            candidates=[_apply_job(j) for j in jobs if j.application_status == "proceeding"],
            problem="This page doesn't match a job you've saved. Pick the job it belongs to.",
        )

    out = ApplyContextOut(job=_apply_job(job))
    if job.application_status != "proceeding":
        out.problem = "Click 'Proceed with Application' for this job in the app first."
        return out

    resume_doc = next(
        (d for d in sorted(job.documents, key=lambda d: d.id, reverse=True) if d.document_type == "resume"),
        None,
    )
    if resume_doc is None:
        out.problem = "Create the tailored resume for this job in the app first."
        return out

    first, last = _split_name(profile.name)
    # Most recent role: a current one (no end date) first, otherwise the latest end/start date.
    recent = max(
        profile.employment_history,
        key=lambda r: (r.end_date is None, r.end_date or dt.date.min, r.start_date or dt.date.min),
        default=None,
    )
    out.candidate = CandidateFacts(
        first_name=first,
        preferred_name=(profile.preferred_name or "").strip() or None,
        recent_title=recent.title if recent else None,
        recent_employer=recent.employer if recent else None,
        last_name=last,
        full_name=profile.name,
        email=profile.email,
        phone=profile.phone,
        location=profile.location,
        linkedin_url=profile.linkedin_url,
    )
    out.resume = ApplyResume(
        document_id=resume_doc.id, filename=Path(resume_doc.local_path).name, format=resume_doc.format
    )
    for answer in db.query(CandidateAnswer).filter(CandidateAnswer.profile_id == profile.id).all():
        raw = answer.value.get("raw") if isinstance(answer.value, dict) else None
        if answer.answer_key in ELIGIBILITY_KEYS:
            out.answers[answer.answer_key] = raw
        elif answer.answer_key.startswith("q:") and isinstance(raw, str) and raw.strip():
            out.learned_answers[answer.answer_key[2:]] = raw
    return out


@router.post("/report", status_code=status.HTTP_204_NO_CONTENT)
def report_fill(payload: ApplyReportIn, db: Session = Depends(get_db)) -> None:
    """Records the questions left blank. Re-running Fill never creates duplicates."""
    job = db.get(Job, payload.job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    existing = {
        q.question_key: q
        for q in db.query(PendingQuestion).filter(PendingQuestion.job_id == job.id).all()
    }
    for field in payload.flagged:
        key = normalize_question(field.label)
        if not key:
            continue
        row = existing.get(key)
        if row is None:
            db.add(
                PendingQuestion(
                    job_id=job.id,
                    label=field.label.strip()[:500],
                    question_key=key[:500],
                    field_type=field.field_type,
                    options=field.options[:50],
                    required=field.required,
                    page_url=(payload.page_url or "")[:1000] or None,
                )
            )
        elif row.status == "dismissed":
            continue
        elif row.status == "answered":
            continue  # already answered; the extension fills it next time
    db.commit()
