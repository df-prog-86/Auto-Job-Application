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
NAME_FILE = "master_name.txt"


def master_dir() -> Path:
    return Path(settings.GENERATED_DOCUMENTS_DIR).resolve().parent / "master_resume"


def master_path() -> Path | None:
    path = master_dir() / MASTER_NAME
    return path if path.exists() else None


def save_master(data: bytes, original_name: str | None = None) -> Path:
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
    # Remember the name the file had when it was uploaded, for the Profile page. Display only.
    name = os.path.basename((original_name or "").replace("\\", "/")).strip()[:200]
    try:
        if name:
            (directory / NAME_FILE).write_text(name, encoding="utf-8")
        elif (directory / NAME_FILE).exists():
            (directory / NAME_FILE).unlink()
    except OSError:
        pass
    return directory / MASTER_NAME


def master_filename() -> str | None:
    try:
        text = (master_dir() / NAME_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def master_status() -> dict:
    """Whether a master is saved and when it was last replaced (for the Profile page)."""
    import datetime as dt

    path = master_path()
    if path is None:
        return {"saved": False, "updated_at": None, "filename": None}
    return {"saved": True, "updated_at": dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat(),
        "filename": master_filename(),
    }
