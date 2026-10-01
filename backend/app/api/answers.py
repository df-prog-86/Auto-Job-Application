"""CandidateAnswer library + deterministic experience summary (spec §13)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.candidate import CandidateAnswer
from app.repositories.profile_repository import get_current_profile
from app.schemas.answers import AnswerOut, AnswerUpsertRequest, ExperienceSummaryResponse
from app.services.onboarding.experience_summary import compute_experience_summary

router = APIRouter(prefix="/api/v1/profile", tags=["answers"])


def _require_profile(db: Session):
    profile = get_current_profile(db)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No profile exists yet. Upload your resume on the Profile page first.",
        )
    return profile


@router.get("/answers", response_model=list[AnswerOut])
def list_answers(db: Session = Depends(get_db)) -> list[AnswerOut]:
    profile = _require_profile(db)
    answers = db.query(CandidateAnswer).filter(CandidateAnswer.profile_id == profile.id).all()
    return [
        AnswerOut(
            answer_key=a.answer_key,
            value_type=a.value_type,
            value=a.value.get("raw"),
            explanatory_text=a.explanatory_text,
            provenance=a.provenance,
            user_confirmed=a.user_confirmed,
        )
        for a in answers
    ]


@router.put("/answers/{answer_key}", response_model=AnswerOut)
def upsert_answer(
    answer_key: str, payload: AnswerUpsertRequest, db: Session = Depends(get_db)
) -> AnswerOut:
    profile = _require_profile(db)

    existing = (
        db.query(CandidateAnswer)
        .filter(CandidateAnswer.profile_id == profile.id, CandidateAnswer.answer_key == answer_key)
        .one_or_none()
    )

    if existing is None:
        existing = CandidateAnswer(
            profile_id=profile.id,
            answer_key=answer_key,
            value_type=payload.value_type,
            value={"raw": payload.value},
            explanatory_text=payload.explanatory_text,
            provenance="user",
            user_confirmed=payload.user_confirmed,
        )
        db.add(existing)
    else:
        existing.value_type = payload.value_type
        existing.value = {"raw": payload.value}
        existing.explanatory_text = payload.explanatory_text
        existing.user_confirmed = payload.user_confirmed

    db.commit()
    db.refresh(existing)
    return AnswerOut(
        answer_key=existing.answer_key,
        value_type=existing.value_type,
        value=existing.value.get("raw"),
        explanatory_text=existing.explanatory_text,
        provenance=existing.provenance,
        user_confirmed=existing.user_confirmed,
    )


@router.get("/experience-summary", response_model=ExperienceSummaryResponse)
def experience_summary(db: Session = Depends(get_db)) -> ExperienceSummaryResponse:
    profile = _require_profile(db)
    return compute_experience_summary(db, profile.id)
