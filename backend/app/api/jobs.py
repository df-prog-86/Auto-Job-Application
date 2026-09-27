"""Read-only job listing (spec §75)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.jobs import Job
from app.schemas.discovery import JobDetailOut, JobOut

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
