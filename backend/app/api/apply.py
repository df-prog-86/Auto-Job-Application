"""
Endpoints the browser extension uses to fill an application page the user
has open (Milestone 6). Everything here is extension-token guarded. The
extension fills what it is sure about and reports the rest back as
questions for the Needs Attention page; it never submits anything.
"""

from __future__ import annotations

import datetime as dt
import re
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
    ApplyCertification,
    ApplyContextOut,
    ApplyEducation,
    ApplyExperience,
    ApplyJob,
    ApplyReportIn,
    LearnedIn,
    ApplyResume,
    CandidateFacts,
)
from app.services.apply.questions import answer_key_for, normalize_question, urls_match
from app.services.resume.role_bullets import match_bullets, resume_roles
from app.services.resume.service import is_safe_document_path

router = APIRouter(prefix="/api/v1/apply", tags=["apply"], dependencies=[Depends(require_extension_auth)])

ELIGIBILITY_KEYS = (
    "work_authorization",
    "sponsorship_required",
    "security_clearance",
    "background_check_ok",
    "criminal_check_ok",
    "drug_screen_ok",
    "age_18_plus",
    "relocation_ok",
    "desired_salary",
    "available_to_start",
    "phone_country",
    "phone_device_type",
    "address_line1",
    "postal_code",
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


def _month(d: dt.date | None) -> str | None:
    return d.strftime("%Y-%m") if d else None


def _history(profile, resume_doc) -> tuple[list[ApplyExperience], list[ApplyEducation]]:
    """Saved roles and schools, newest first. Role descriptions come from the resume used for this job."""
    roles = sorted(
        profile.employment_history,
        key=lambda r: (r.end_date is None, r.end_date or dt.date.min, r.start_date or dt.date.min),
        reverse=True,
    )
    bullets: list[list[str] | None] = [None] * len(roles)
    if resume_doc is not None and resume_doc.format == "docx" and is_safe_document_path(resume_doc.local_path):
        bullets = match_bullets([(r.employer, r.title) for r in roles], resume_roles(resume_doc.local_path))
    experience = [
        ApplyExperience(
            title=r.title,
            employer=r.employer,
            location=r.location,
            start_date=_month(r.start_date),
            end_date=_month(r.end_date),
            current=r.end_date is None,
            description="\n".join(f"\u2022 {b}" for b in (bullets[i] or [])),
        )
        for i, r in enumerate(roles)
    ]
    schools = sorted(profile.education, key=lambda e: (e.end_date or dt.date.min, e.start_date or dt.date.min), reverse=True)
    education = [
        ApplyEducation(
            institution=e.institution,
            degree=e.degree,
            degree_short=e.degree_short,
            field=e.field,
            start_date=_month(e.start_date),
            end_date=_month(e.end_date),
            gpa=e.gpa,
        )
        for e in schools
    ]
    return experience, education


MAX_SKILLS = 25


def _certifications(profile) -> list[ApplyCertification]:
    certs = sorted(profile.certifications, key=lambda c: c.date or dt.date.min, reverse=True)
    return [
        ApplyCertification(
            name=c.certification,
            issuer=c.issuer,
            issued=c.date.isoformat() if c.date else None,
            expires=c.expiration.isoformat() if c.expiration else None,
        )
        for c in certs
        if (c.certification or "").strip()
    ]


def _skills(profile, job: Job) -> list[str]:
    """The candidate's skills for a skills box, those the posting mentions first (never invented)."""
    text = (job.description or "").lower()
    seen: set[str] = set()
    names: list[str] = []
    for skill in profile.skills:
        name = (skill.canonical_skill or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)

    def mentioned(name: str) -> bool:
        return bool(text) and re.search(rf"(?<![a-z0-9]){re.escape(name.lower())}(?![a-z0-9])", text) is not None

    ranked = [n for n in names if mentioned(n)] + [n for n in names if not mentioned(n)]
    return ranked[:MAX_SKILLS]


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
        out.problem = "Choose a resume for this job in the app first (tailored or your original)."
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
    out.experience, out.education = _history(profile, resume_doc)
    out.skills = _skills(profile, job)
    out.certifications = _certifications(profile)
    for answer in db.query(CandidateAnswer).filter(CandidateAnswer.profile_id == profile.id).all():
        raw = answer.value.get("raw") if isinstance(answer.value, dict) else None
        if answer.answer_key in ELIGIBILITY_KEYS:
            out.answers[answer.answer_key] = raw
        elif answer.answer_key.startswith("q:") and isinstance(raw, str) and raw.strip():
            out.learned_answers[answer.answer_key[2:]] = raw
    return out


# Questions whose answers must be given fresh each time (agreements, signatures, identifiers, secrets).
_NEVER_REMEMBER = re.compile(
    r"password|passcode|\bssn\b|social security|card number|account number|routing|passport|"
    r"certify|attest|acknowledg|\bagree\b|consent|signature|sign here|i understand|terms|"
    r"\b(ever|convicted|arrested|felony|failed)\b",
    re.I,
)


@router.post("/learned")
def save_learned(payload: LearnedIn, db: Session = Depends(get_db)) -> dict[str, int]:
    """
    Remembers answers the person gave themselves on a form, so the same
    question is filled in next time. Anything that looks like an agreement,
    a secret or a history question is refused here as well.
    """
    profile = get_current_profile(db)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile has been created yet.")
    saved = 0
    for item in payload.answers[:20]:
        label = item.label.strip()
        value = item.value.strip()
        key = normalize_question(label)
        if not key or not value or len(value) > 300 or _NEVER_REMEMBER.search(label):
            continue
        answer_key = answer_key_for(key)
        existing = (
            db.query(CandidateAnswer)
            .filter(CandidateAnswer.profile_id == profile.id, CandidateAnswer.answer_key == answer_key)
            .one_or_none()
        )
        if existing is None:
            db.add(
                CandidateAnswer(
                    profile_id=profile.id,
                    answer_key=answer_key,
                    value_type="str",
                    value={"raw": value},
                    explanatory_text=label[:500],
                    provenance="extension",
                    user_confirmed=True,
                )
            )
        else:
            existing.value = {"raw": value}
            existing.explanatory_text = existing.explanatory_text or label[:500]
            existing.user_confirmed = True
        # The question is no longer waiting on anyone.
        for pending in db.query(PendingQuestion).filter(
            PendingQuestion.question_key == key[:500], PendingQuestion.status == "open"
        ):
            pending.status = "answered"
            pending.answer_text = value
        saved += 1
    db.commit()
    return {"saved": saved}


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
