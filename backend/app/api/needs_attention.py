"""Needs Attention: the application questions the extension left blank for the candidate."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.candidate import CandidateAnswer
from app.models.jobs import Job
from app.models.questions import PendingQuestion
from app.repositories.profile_repository import get_current_profile
from app.schemas.apply import AnswerQuestionIn, PendingQuestionOut
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


@router.get("", response_model=list[PendingQuestionOut])
def list_open(db: Session = Depends(get_db)) -> list[PendingQuestionOut]:
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
