"""
Scheduled discovery (spec §18): runs automatically on an interval,
independent of whether the extension/Chrome is even open — discovery is
read-only polling of public job feeds, not application execution, so it
isn't gated by the automation PAUSED/REVIEW/AUTO mode. It only ever writes
to the local jobs table; it never touches an employer's application system.
"""

from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.services.discovery.pipeline import run_discovery

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_discovery_job() -> None:
    db = SessionLocal()
    try:
        result = run_discovery(db)
        logger.info(
            "Scheduled discovery run: %s employers checked, %s jobs created, %s updated, %s errors",
            result.employers_checked,
            result.jobs_created,
            result.jobs_updated,
            len(result.errors),
        )
    except Exception:
        logger.exception("Scheduled discovery run failed")
    finally:
        db.close()


def _run_job_cache_refresh() -> None:
    """Reads the employers whose saved job lists are out of date (a few at a time, politely). Safe to run often: only due ones are read."""
    from app.services.jobcache import service

    try:
        service.run_refresh()
    except Exception:
        logger.exception("Scheduled job-list refresh failed")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _run_discovery_job,
        "interval",
        hours=settings.DISCOVERY_INTERVAL_HOURS,
        id="discovery_run",
        # First automatic run fires one full interval from now; use
        # POST /api/v1/discovery/run for an immediate, on-demand run.
        coalesce=True,
        max_instances=1,
    )
    if settings.JOB_CACHE_AUTO_REFRESH:
        # First read shortly after the app opens (a laptop that was asleep catches up), then on a steady interval.
        scheduler.add_job(
            _run_job_cache_refresh,
            "interval",
            hours=max(settings.JOB_CACHE_REFRESH_HOURS, 1),
            id="job_cache_refresh",
            next_run_time=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=45),
            coalesce=True,
            max_instances=1,
        )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
