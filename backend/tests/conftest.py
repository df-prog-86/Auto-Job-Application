from __future__ import annotations

import os
import tempfile
from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def _no_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Force "no LLM provider configured" regardless of the developer's local
    backend/.env. Without this, a real LLM_API_BASE_URL/LLM_API_KEY_REF in
    .env makes the settings singleton (loaded once at process start) look
    configured to every test in this process — which doesn't just change
    test_resume_parse_without_llm_configured_returns_503's expected status
    code, it makes that test send a real resume to a real provider using
    the developer's real API key on every test run.
    """
    from app.config import settings

    for attr in (
        "LLM_API_BASE_URL",
        "LLM_API_KEY_REF",
        "PRIMARY_FAST_MODEL",
        "FALLBACK_FAST_MODEL",
        "ESCALATION_MODEL",
    ):
        monkeypatch.setattr(settings, attr, None)


@pytest.fixture(autouse=True)
def _isolated_job_cache(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Every test gets its own empty job cache file, so tests never touch (or depend on) the real backend/data/job_cache.db."""
    from app.config import settings

    monkeypatch.setattr(settings, "JOB_CACHE_PATH", str(tmp_path / "job_cache.db"))
    monkeypatch.setattr(settings, "JOB_CACHE_DISABLED_SYSTEMS", "")
    monkeypatch.setattr(settings, "JOB_SEARCH_AI", "always")
    monkeypatch.setattr(settings, "JOB_CACHE_AUTO_REFRESH", False)  # tests never read real employer sites


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
