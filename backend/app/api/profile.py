"""
Profile/onboarding API (spec §75): resume upload/parse, review-and-commit,
and profile CRUD. This is Milestone 2's user-facing surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.profile_repository import commit_profile, get_current_profile
from app.models.candidate import Certification, Education, EmploymentHistory, Skill
from app.schemas.profile import (
    CommitProfileRequest,
    CertificationIn,
    EducationIn,
    EmploymentIn,
    MasterRoleOut,
    ProfileOut,
    SkillIn,
    ProfileUpdateRequest,
    ResumeParseResponse,
)
from app.services.llm.exceptions import LLMNotConfiguredError, StructuredOutputError
from app.services.onboarding.pipeline import ResumeValidationError, parse_resume
from app.services.onboarding.claims import parse_partial_date
from app.services.resume.master import master_status, save_master
from app.services.resume.master_view import master_roles

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.post("/resume/parse", response_model=ResumeParseResponse)
async def parse_resume_endpoint(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> ResumeParseResponse:
    data = await file.read()
    try:
        response = await parse_resume(db, file.filename or "resume", data)
        # A Word upload becomes the master that tailored resumes are copied
        # from (layout preserved). Saved only after it parsed successfully,
        # and kept on this computer only.
        if (file.filename or "").lower().endswith(".docx"):
            save_master(data)
        return response
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


@router.get("/master")
def get_master_status() -> dict:
    return master_status()


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
        # Name and email can't be blank; ignore an attempt to clear them.
        if field in ("name", "email") and not (value or "").strip():
            continue
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.get("/master/roles", response_model=list[MasterRoleOut])
def get_master_roles() -> list[MasterRoleOut]:
    """Bullets per role from the saved master Word resume (read-only)."""
    return [MasterRoleOut(**r) for r in master_roles()]


def _need_profile(db: Session):
    profile = get_current_profile(db)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile has been created yet.")
    return profile


def _apply_dates(row, data: dict) -> None:
    for key in ("start_date", "end_date"):
        if key in data:
            setattr(row, key, parse_partial_date((data[key] or "").strip() or None))


@router.post("/employment", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def add_employment(payload: EmploymentIn, db: Session = Depends(get_db)) -> ProfileOut:
    profile = _need_profile(db)
    data = payload.model_dump(exclude_unset=True)
    row = EmploymentHistory(
        profile_id=profile.id,
        employer=(data.get("employer") or "").strip(),
        title=(data.get("title") or "").strip(),
        location=data.get("location"),
    )
    _apply_dates(row, data)
    db.add(row)
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.patch("/employment/{entry_id}", response_model=ProfileOut)
def update_employment(entry_id: int, payload: EmploymentIn, db: Session = Depends(get_db)) -> ProfileOut:
    profile = _need_profile(db)
    row = db.get(EmploymentHistory, entry_id)
    if row is None or row.profile_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    data = payload.model_dump(exclude_unset=True)
    for field in ("employer", "title"):
        if field in data and (data[field] or "").strip():
            setattr(row, field, data[field].strip())  # required; ignore an attempt to blank it
    if "location" in data:
        row.location = (data["location"] or "").strip() or None
    _apply_dates(row, data)
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.delete("/employment/{entry_id}", response_model=ProfileOut)
def delete_employment(entry_id: int, db: Session = Depends(get_db)) -> ProfileOut:
    profile = _need_profile(db)
    row = db.get(EmploymentHistory, entry_id)
    if row is None or row.profile_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    db.delete(row)
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.post("/education", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def add_education(payload: EducationIn, db: Session = Depends(get_db)) -> ProfileOut:
    profile = _need_profile(db)
    data = payload.model_dump(exclude_unset=True)
    row = Education(
        profile_id=profile.id,
        institution=(data.get("institution") or "").strip(),
        degree=data.get("degree"),
        degree_short=(data.get("degree_short") or "").strip() or None,
        field=data.get("field"),
        gpa=(data.get("gpa") or "").strip() or None,
        source="manual",
    )
    _apply_dates(row, data)
    db.add(row)
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.patch("/education/{entry_id}", response_model=ProfileOut)
def update_education(entry_id: int, payload: EducationIn, db: Session = Depends(get_db)) -> ProfileOut:
    profile = _need_profile(db)
    row = db.get(Education, entry_id)
    if row is None or row.profile_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found.")
    data = payload.model_dump(exclude_unset=True)
    if "institution" in data and (data["institution"] or "").strip():
        row.institution = data["institution"].strip()
    for field in ("degree", "degree_short", "field", "gpa"):
        if field in data:
            setattr(row, field, (data[field] or "").strip() or None)
    _apply_dates(row, data)
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.delete("/education/{entry_id}", response_model=ProfileOut)
def delete_education(entry_id: int, db: Session = Depends(get_db)) -> ProfileOut:
    profile = _need_profile(db)
    row = db.get(Education, entry_id)
    if row is None or row.profile_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found.")
    db.delete(row)
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


def _apply_cert_dates(row: Certification, data: dict) -> None:
    for key in ("date", "expiration"):
        if key in data:
            setattr(row, key, parse_partial_date((data[key] or "").strip() or None))


@router.post("/certifications", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def add_certification(payload: CertificationIn, db: Session = Depends(get_db)) -> ProfileOut:
    profile = _need_profile(db)
    data = payload.model_dump(exclude_unset=True)
    row = Certification(
        profile_id=profile.id,
        certification=(data.get("certification") or "").strip(),
        issuer=(data.get("issuer") or "").strip() or None,
        source="manual",
    )
    _apply_cert_dates(row, data)
    db.add(row)
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.patch("/certifications/{entry_id}", response_model=ProfileOut)
def update_certification(entry_id: int, payload: CertificationIn, db: Session = Depends(get_db)) -> ProfileOut:
    profile = _need_profile(db)
    row = db.get(Certification, entry_id)
    if row is None or row.profile_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certification not found.")
    data = payload.model_dump(exclude_unset=True)
    if "certification" in data and (data["certification"] or "").strip():
        row.certification = data["certification"].strip()  # required; ignore an attempt to blank it
    if "issuer" in data:
        row.issuer = (data["issuer"] or "").strip() or None
    _apply_cert_dates(row, data)
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.delete("/certifications/{entry_id}", response_model=ProfileOut)
def delete_certification(entry_id: int, db: Session = Depends(get_db)) -> ProfileOut:
    profile = _need_profile(db)
    row = db.get(Certification, entry_id)
    if row is None or row.profile_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certification not found.")
    db.delete(row)
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.post("/skills", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def add_skill(payload: SkillIn, db: Session = Depends(get_db)) -> ProfileOut:
    profile = _need_profile(db)
    name = payload.canonical_skill.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Enter a skill.")
    if not any(s.canonical_skill.lower() == name.lower() for s in profile.skills):
        db.add(Skill(profile_id=profile.id, canonical_skill=name, candidate_confirmed=True, source="manual"))
        db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.delete("/skills/{skill_id}", response_model=ProfileOut)
def delete_skill(skill_id: int, db: Session = Depends(get_db)) -> ProfileOut:
    profile = _need_profile(db)
    row = db.get(Skill, skill_id)
    if row is None or row.profile_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found.")
    db.delete(row)
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)
