"""
Profile/onboarding API (spec §75): resume upload/parse, review-and-commit,
and profile CRUD. This is Milestone 2's user-facing surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.profile_repository import commit_profile, get_current_profile
from app.schemas.profile import (
    CommitProfileRequest,
    ProfileOut,
    ProfileUpdateRequest,
    ResumeParseResponse,
)
from app.services.llm.exceptions import LLMNotConfiguredError, StructuredOutputError
from app.services.onboarding.pipeline import ResumeValidationError, parse_resume

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.post("/resume/parse", response_model=ResumeParseResponse)
async def parse_resume_endpoint(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> ResumeParseResponse:
    data = await file.read()
    try:
        return await parse_resume(db, file.filename or "resume", data)
    except ResumeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No LLM provider is configured yet, so resumes can't be parsed automatically. "
                "Set PRIMARY_FAST_MODEL and the related LLM_* settings, then try again."
            ),
        ) from exc
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Couldn't extract structured data from this resume after retrying: {exc}",
        ) from exc


@router.post("/commit", response_model=ProfileOut)
def commit_profile_endpoint(
    payload: CommitProfileRequest, db: Session = Depends(get_db)
) -> ProfileOut:
    profile = commit_profile(db, payload)
    return ProfileOut.model_validate(profile)


@router.get("", response_model=ProfileOut)
def get_profile(db: Session = Depends(get_db)) -> ProfileOut:
    profile = get_current_profile(db)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile has been created yet.")
    return ProfileOut.model_validate(profile)


@router.patch("", response_model=ProfileOut)
def update_profile(payload: ProfileUpdateRequest, db: Session = Depends(get_db)) -> ProfileOut:
    profile = get_current_profile(db)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile has been created yet.")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)
