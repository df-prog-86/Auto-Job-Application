"""Search profile CRUD (spec §4.3, §75)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.search import SearchProfile
from app.schemas.discovery import SearchProfileIn, SearchProfileOut, SearchProfileUpdate

router = APIRouter(prefix="/api/v1/search-profiles", tags=["search-profiles"])


@router.get("", response_model=list[SearchProfileOut])
def list_search_profiles(db: Session = Depends(get_db)) -> list[SearchProfileOut]:
    profiles = db.query(SearchProfile).order_by(SearchProfile.id).all()
    return [SearchProfileOut.model_validate(p) for p in profiles]


@router.post("", response_model=SearchProfileOut, status_code=status.HTTP_201_CREATED)
def create_search_profile(payload: SearchProfileIn, db: Session = Depends(get_db)) -> SearchProfileOut:
    profile = SearchProfile(**payload.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return SearchProfileOut.model_validate(profile)


@router.patch("/{profile_id}", response_model=SearchProfileOut)
def update_search_profile(
    profile_id: int, payload: SearchProfileUpdate, db: Session = Depends(get_db)
) -> SearchProfileOut:
    profile = db.get(SearchProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search profile not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return SearchProfileOut.model_validate(profile)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_search_profile(profile_id: int, db: Session = Depends(get_db)) -> None:
    profile = db.get(SearchProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search profile not found.")
    db.delete(profile)
    db.commit()
