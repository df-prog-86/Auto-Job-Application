"""
The candidate's master resume: the single source of truth for tailoring.
Saved exactly as uploaded, never modified. Every tailored resume is made
from a fresh copy of this file, so tailored versions never build on each
other. Stays on this computer (backend/data/master_resume/).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.config import settings

MASTER_NAME = "master.docx"


def master_dir() -> Path:
    return Path(settings.GENERATED_DOCUMENTS_DIR).resolve().parent / "master_resume"


def master_path() -> Path | None:
    path = master_dir() / MASTER_NAME
    return path if path.exists() else None


def save_master(data: bytes) -> Path:
    """Atomic write: the old master is replaced only once the new file is fully on disk."""
    directory = master_dir()
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, directory / MASTER_NAME)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return directory / MASTER_NAME


def master_status() -> dict:
    """Whether a master is saved and when it was last replaced (for the Profile page)."""
    import datetime as dt

    path = master_path()
    if path is None:
        return {"saved": False, "updated_at": None}
    return {"saved": True, "updated_at": dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat()}
