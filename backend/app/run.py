"""
Entrypoint for local/packaged runs (spec §88 Startup Behavior). Handles the
single-instance lock and migration-at-startup steps that belong before
uvicorn ever binds a socket. Kept deliberately thin — packaging (Milestone
12) wraps this, it doesn't replace it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn
from filelock import FileLock, Timeout

from app.config import settings

LOCK_PATH = Path(settings.DATABASE_PATH).parent / ".job-agent.lock"


def main() -> None:
    lock = FileLock(str(LOCK_PATH))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        print(
            "Another instance of the Job Agent backend is already running "
            f"(lock held at {LOCK_PATH}). Exiting.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        # Migrations are applied by the packaged installer / dev `alembic
        # upgrade head` today; auto-upgrade-on-boot is wired in with
        # Milestone 12 once the upgrade path itself is tested.
        uvicorn.run(
            "app.main:app",
            host=settings.LOCAL_API_HOST,
            port=settings.LOCAL_API_PORT,
            reload=settings.APP_ENV == "development",
        )
    finally:
        lock.release()


if __name__ == "__main__":
    main()
