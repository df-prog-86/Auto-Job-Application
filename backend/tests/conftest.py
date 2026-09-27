from __future__ import annotations

import os
import tempfile
from collections.abc import Generator

import pytest


@pytest.fixture()
def temp_db_path() -> Generator[str, None, None]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture()
def app_and_db(temp_db_path, monkeypatch):
    """
    Builds a fully isolated FastAPI app + SQLite DB per test. Config is
    re-read and the engine re-created against a temp file so tests never
    touch the real backend/data/job_agent.db.
    """
    monkeypatch.setenv("DATABASE_PATH", temp_db_path)

    # Reload modules that captured settings/engine at import time.
    import importlib

    import app.config as config_module

    importlib.reload(config_module)

    import app.database as database_module

    importlib.reload(database_module)

    from app.database import Base

    Base.metadata.create_all(bind=database_module.engine)

    import app.main as main_module

    importlib.reload(main_module)

    from fastapi.testclient import TestClient

    client = TestClient(main_module.app)
    yield client, database_module.SessionLocal

    client.close()
