"""The Employers panel on Job Search: which employers' job lists are saved and searched, add one by link, switch one off."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.job_search import AddEmployerIn, EmployerOut, EmployersOut, EnabledIn
from app.services.jobcache import service
from app.services.jobcache.store import JobCache

router = APIRouter(prefix="/api/v1/job-search/employers", tags=["job-search"])


def _when(ts: int | None) -> dt.datetime | None:
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc) if ts else None


def _out(row: dict) -> EmployerOut:
    return EmployerOut(
        id=row["id"],
        name=row["name"],
        system=row["ats"],
        enabled=bool(row["enabled"]),
        status=row["status"],
        open_jobs=row["open_count"],
        last_read=_when(row["last_ok"]),
        last_error=row["last_error"],
        source=row["source"],
    )


def _listing(query: str | None = None, limit: int = 100) -> EmployersOut:
    cache = JobCache()
    rows = cache.list_employers(query, limit)
    counts = cache.counts()
    state = service.refresh_state()
    return EmployersOut(
        employers=[_out(r) for r in rows],
        total_employers=counts["employers"],
        total_postings=counts["postings"],
        refreshing=state["running"],
        refresh_done=state["done"],
        refresh_total=state["total"],
        last_refresh=dt.datetime.fromisoformat(state["finished_at"]) if state["finished_at"] else None,
        disabled_systems=sorted(service.disabled_systems()),
    )


@router.get("", response_model=EmployersOut)
def list_employers(q: str | None = None, limit: int = 100, db: Session = Depends(get_db)) -> EmployersOut:
    """The saved employers (the busiest first). The first time, it also adds the employers behind the jobs you have saved and results you were shown."""
    cache = JobCache()
    if not cache.list_employers(limit=1):
        service.seed_from_app(db)
        service.refresh_in_background(seed=False)
    return _listing(q, max(1, min(limit, 500)))


@router.post("", response_model=EmployerOut, status_code=status.HTTP_201_CREATED)
async def add_employer(payload: AddEmployerIn) -> EmployerOut:
    try:
        row = await service.add_employer(payload.url.strip())
    except service.AddEmployerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _out(row)


@router.patch("/{employer_id}", response_model=EmployerOut)
def set_enabled(employer_id: int, payload: EnabledIn) -> EmployerOut:
    cache = JobCache()
    if not cache.set_enabled(employer_id, payload.enabled):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That employer is no longer on the list.")
    row = cache.get_employer(employer_id)
    assert row is not None
    return _out(row)


@router.post("/refresh", response_model=EmployersOut)
def refresh_now(db: Session = Depends(get_db)) -> EmployersOut:
    """Reads every employer that is due, now, in the background. Employers you have not had read yet go first."""
    cache = JobCache()
    with cache.session() as conn:  # "refresh now" means now: everything becomes due
        conn.execute("UPDATE employers SET next_check = 0 WHERE enabled = 1 AND status IN ('new', 'ok', 'error')")
    service.seed_from_app(db)
    service.refresh_in_background(seed=False, force=True)
    return _listing()
