"""
One-time cleanup of jobs you already saved: "&amp;" turned into "&", employer codes removed ("9998 Ochsner" -> "Ochsner"),
and a place that says virtual or remote no longer paired with "hybrid".

  cd backend
  python -m scripts.tidy_jobs            # shows what would change; changes nothing
  python -m scripts.tidy_jobs --apply    # makes a backup copy of your job database first, then applies the changes

It also lists jobs saved twice (same employer, title and place). It never deletes anything.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.jobs import Job
from app.services.jobcache.text import clean_company, clean_title, reconcile_place, tidy_place


def planned_changes(job: Job) -> dict[str, str | None]:
    """Fields of one saved job that tidying would change, with the new value."""
    changes: dict[str, str | None] = {}
    company = clean_company(job.company) or job.company
    if company != job.company:
        changes["company"] = company
    title = clean_title(job.title, job.company) or job.title
    if title != job.title:
        changes["title"] = title
    place = tidy_place(job.location) if job.location else job.location
    place, work_type = reconcile_place(place, job.remote_type)
    if place != job.location:
        changes["location"] = place
    if work_type != job.remote_type:
        changes["remote_type"] = work_type
    return changes


def tidy_jobs(db: Session, apply: bool) -> list[tuple[int, dict[str, str | None]]]:
    out: list[tuple[int, dict[str, str | None]]] = []
    for job in db.scalars(select(Job)):
        changes = planned_changes(job)
        if not changes:
            continue
        out.append((job.id, changes))
        if apply:
            for field, value in changes.items():
                setattr(job, field, value)
    if apply:
        db.commit()
    return out


def duplicate_groups(db: Session) -> list[list[Job]]:
    """Jobs saved more than once: same employer, title and place once tidied."""
    seen: dict[tuple[str, str, str], list[Job]] = {}
    for job in db.scalars(select(Job)):
        key = (
            "".join(ch for ch in (clean_company(job.company) or "").lower() if ch.isalnum()),
            "".join(ch for ch in (clean_title(job.title, job.company) or "").lower() if ch.isalnum()),
            "".join(ch for ch in (tidy_place(job.location) or "").lower() if ch.isalnum()),
        )
        seen.setdefault(key, []).append(job)
    return [group for group in seen.values() if len(group) > 1]


def backup(path: Path) -> Path:
    target = path.with_name(f"{path.stem}.backup-{time.strftime('%Y%m%d-%H%M%S')}{path.suffix}")
    src = sqlite3.connect(path)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="make the changes (after backing up the database)")
    args = parser.parse_args()

    from app.database import SessionLocal

    db_path = Path(settings.DATABASE_PATH)
    if args.apply:
        copy = backup(db_path)
        print(f"Backup saved: {copy}")
    with SessionLocal() as db:
        changes = tidy_jobs(db, apply=args.apply)
        print(f"{len(changes)} saved job(s) {'changed' if args.apply else 'would change'}.")
        for job_id, fields in changes[:40]:
            print(f"  job {job_id}: " + "; ".join(f"{k} -> {v!r}" for k, v in fields.items()))
        if len(changes) > 40:
            print(f"  ... and {len(changes) - 40} more")
        groups = duplicate_groups(db)
        print(f"{len(groups)} job(s) saved more than once (nothing deleted):")
        for group in groups:
            print("  " + " | ".join(f"#{j.id} {j.company} - {j.title}" for j in group[:3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
