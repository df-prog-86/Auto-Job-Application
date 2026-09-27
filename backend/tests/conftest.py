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
def app_and_db(temp_db_path):
    """
    Builds a fully isolated FastAPI app + SQLite DB per test. A fresh engine is
    created against a temp file and swapped in via a `get_db` dependency
    override, so tests never touch the real backend/data/job_agent.db.

    (Reloading app.database instead would create a new, empty `Base` that the
    already-imported models aren't registered on, so create_all() would make
    no tables.)
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import models  # noqa: F401 - ensures all models are registered on Base.metadata
    from app.database import Base, get_db
    from app.main import app

    engine = create_engine(
        f"sqlite:///{temp_db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def _get_test_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_test_db

    # LocalOnlyMiddleware rejects TestClient's default "testserver" Host header.
    client = TestClient(app, base_url="http://127.0.0.1")
    yield client, SessionLocal

    client.close()
    app.dependency_overrides.clear()
    engine.dispose()
