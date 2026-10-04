"""Needs Attention: the application questions the extension left blank for the candidate."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.candidate import CandidateAnswer
from app.models.jobs import Job
from app.models.questions import PendingQuestion
from app.repositories.profile_repository import get_current_profile
from app.schemas.apply import AnswerQuestionIn, ClearQuestionsIn, PendingQuestionOut
from app.services.apply.questions import answer_key_for

router = APIRouter(prefix="/api/v1/needs-attention", tags=["needs-attention"])


def _out(q: PendingQuestion, job: Job) -> PendingQuestionOut:
    return PendingQuestionOut(
        id=q.id,
        job_id=q.job_id,
        job_title=job.title,
        company=job.company,
        label=q.label,
        field_type=q.field_type,
        options=list(q.options or []),
        required=q.required,
        status=q.status,
        answer_text=q.answer_text,
    )


# Questions the Profile now answers on its own: question text -> the saved answer that covers it.
_COVERED_BY_PROFILE = {
    "address line 1": "address_line1",
    "street address": "address_line1",
    "postal code": "postal_code",
    "zip code": "postal_code",
    "zip postal code": "postal_code",
    "phone device type": "phone_device_type",
    "phone country code": "phone_country",
}


def _settle_covered(db: Session) -> None:
    """Closes open questions whose answer the person has since saved on their Profile."""
    profile = get_current_profile(db)
    if profile is None:
        return
    saved = {
        a.answer_key: a.value.get("raw")
        for a in db.query(CandidateAnswer).filter(CandidateAnswer.profile_id == profile.id).all()
        if isinstance(a.value, dict)
    }
    changed = False
    for q in db.query(PendingQuestion).filter(PendingQuestion.status == "open").all():
        key = _COVERED_BY_PROFILE.get(q.question_key)
        value = saved.get(key) if key else None
        if isinstance(value, str) and value.strip():
            q.status = "answered"
            q.answer_text = value.strip()
            changed = True
    if changed:
        db.commit()


@router.get("", response_model=list[PendingQuestionOut])
def list_open(db: Session = Depends(get_db)) -> list[PendingQuestionOut]:
    _settle_covered(db)
    rows = (
        db.query(PendingQuestion, Job)
        .join(Job, Job.id == PendingQuestion.job_id)
        .filter(PendingQuestion.status == "open")
        .order_by(PendingQuestion.id.desc())
        .all()
    )
    return [_out(q, job) for q, job in rows]


def _get(db: Session, question_id: int) -> tuple[PendingQuestion, Job]:
    q = db.get(PendingQuestion, question_id)
    job = db.get(Job, q.job_id) if q else None
    if q is None or job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found.")
    return q, job


@router.post("/{question_id}/answer", response_model=PendingQuestionOut)
def answer_question(
    question_id: int, payload: AnswerQuestionIn, db: Session = Depends(get_db)
) -> PendingQuestionOut:
    """Saves the answer and remembers it, so the same question is filled automatically next time."""
    text = payload.answer.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Type an answer first.")
    q, job = _get(db, question_id)
    profile = get_current_profile(db)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile has been created yet.")

    key = answer_key_for(q.question_key)
    existing = (
        db.query(CandidateAnswer)
        .filter(CandidateAnswer.profile_id == profile.id, CandidateAnswer.answer_key == key)
        .one_or_none()
    )
    if existing is None:
        db.add(
            CandidateAnswer(
                profile_id=profile.id,
                answer_key=key,
                value_type="str",
                value={"raw": text},
                provenance="needs_attention",
                user_confirmed=True,
            )
        )
    else:
        existing.value = {"raw": text}
        existing.user_confirmed = True

    # The same question can be waiting on several jobs; one answer settles them all.
    for other in db.query(PendingQuestion).filter(
        PendingQuestion.question_key == q.question_key, PendingQuestion.status == "open"
    ):
        other.status = "answered"
        other.answer_text = text
    db.commit()
    db.refresh(q)
    return _out(q, job)


@router.post("/{question_id}/dismiss", response_model=PendingQuestionOut)
def dismiss_question(question_id: int, db: Session = Depends(get_db)) -> PendingQuestionOut:
    q, job = _get(db, question_id)
    q.status = "dismissed"
    db.commit()
    db.refresh(q)
    return _out(q, job)


@router.post("/clear")
def clear_questions(payload: ClearQuestionsIn, db: Session = Depends(get_db)) -> dict[str, int]:
    """
    Clears open questions without answering them. They are only dismissed, so if
    the same question comes up on a later application it is listed again.
    """
    query = db.query(PendingQuestion).filter(PendingQuestion.status == "open")
    if payload.ids is not None:
        query = query.filter(PendingQuestion.id.in_(payload.ids))
    cleared = 0
    for q in query.all():
        q.status = "dismissed"
        cleared += 1
    db.commit()
    return {"cleared": cleared}
