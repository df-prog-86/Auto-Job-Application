"""
FastAPI application factory. Binds to 127.0.0.1 only (spec §8.2) — see
run.py / the packaged entrypoint for the actual uvicorn.run() call, which is
the one place the host is passed and must never be 0.0.0.0 outside explicit
controlled dev use.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import answers, automation, discovery, jobs, profile, search_profiles, system
from app.config import settings
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.security.middleware import LocalOnlyMiddleware

DASHBOARD_DIST = Path(__file__).resolve().parent.parent.parent / "dashboard" / "dist"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Discovery scheduling runs regardless of automation mode (spec §18) —
    # it only ever reads public job feeds and writes to the local jobs
    # table, never touches an employer's application system. Skipped
    # entirely under pytest, where each test builds its own isolated app.
    if settings.APP_ENV != "test":
        start_scheduler()
    yield
    stop_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Job Agent Backend",
        version="0.1.0",
        docs_url="/api/docs" if settings.APP_ENV != "production" else None,
        lifespan=_lifespan,
    )

    app.add_middleware(LocalOnlyMiddleware)

    # The extension origin is the only cross-origin caller this API expects;
    # the dashboard is served same-origin by this same process (spec §14).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.EXTENSION_ORIGIN_ALLOWLIST or [],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Extension-Token"],
    )

    app.include_router(system.router)
    app.include_router(automation.router)
    app.include_router(profile.router)
    app.include_router(answers.router)
    app.include_router(search_profiles.router)
    app.include_router(discovery.router)
    app.include_router(jobs.router)

    # Serve the built dashboard, once it exists, at /app (spec §14).
    if DASHBOARD_DIST.exists():
        app.mount("/app", StaticFiles(directory=str(DASHBOARD_DIST), html=True), name="dashboard")

    return app


app = create_app()
