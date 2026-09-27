"""Employer watchlist CRUD and discovery-run trigger (spec §16-18, §75)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.discovery import TargetEmployer
from app.schemas.discovery import DiscoveryRunOut, TargetEmployerIn, TargetEmployerOut
from app.services.discovery.compliance import SOURCE_REGISTRY
from app.services.discovery.pipeline import run_discovery

router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])

SUPPORTED_ATS = set(SOURCE_REGISTRY.keys())


@router.get("/employers", response_model=list[TargetEmployerOut])
def list_target_employers(db: Session = Depends(get_db)) -> list[TargetEmployerOut]:
    employers = db.query(TargetEmployer).order_by(TargetEmployer.id).all()
    return [TargetEmployerOut.model_validate(e) for e in employers]


@router.post("/employers", response_model=TargetEmployerOut, status_code=status.HTTP_201_CREATED)
def add_target_employer(payload: TargetEmployerIn, db: Session = Depends(get_db)) -> TargetEmployerOut:
    if payload.ats not in SUPPORTED_ATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported ATS '{payload.ats}'. Supported: {sorted(SUPPORTED_ATS)}.",
        )
    employer = TargetEmployer(**payload.model_dump())
    db.add(employer)
    db.commit()
    db.refresh(employer)
    return TargetEmployerOut.model_validate(employer)


@router.delete("/employers/{employer_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_target_employer(employer_id: int, db: Session = Depends(get_db)) -> None:
    employer = db.get(TargetEmployer, employer_id)
    if employer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employer not found.")
    db.delete(employer)
    db.commit()


@router.post("/run", response_model=DiscoveryRunOut)
def trigger_discovery_run(db: Session = Depends(get_db)) -> DiscoveryRunOut:
    result = run_discovery(db)
    return DiscoveryRunOut(
        employers_checked=result.employers_checked,
        employers_failed=result.employers_failed,
        postings_fetched=result.postings_fetched,
        postings_matched=result.postings_matched,
        jobs_created=result.jobs_created,
        jobs_updated=result.jobs_updated,
        errors=result.errors,
    )
