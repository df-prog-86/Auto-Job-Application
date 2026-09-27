"""
System-level endpoints (spec §74, §8.3): health, version/protocol
compatibility, and extension pairing. These are the first endpoints the
extension calls, so they double as the Milestone 1 acceptance surface.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.models.system import AutomationState
from app.services.security.pairing import (
    generate_pairing_secret,
    issue_extension_token,
)

router = APIRouter(prefix="/api/v1", tags=["system"])

BACKEND_VERSION = "0.1.0"
API_VERSION = "1"
SCHEMA_VERSION = "1"  # bumped alongside each Alembic head that changes shape extensions rely on

# In-memory for now; the pairing secret is meant to be single-use and
# short-lived, not a durable credential — persisting it would defeat the
# point. A production run surfaces this value to the user via the dashboard
# on first launch (Milestone 10).
_current_pairing_secret: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    time: str


class VersionResponse(BaseModel):
    backend_version: str
    api_version: str
    schema_version: str


class PairingSecretResponse(BaseModel):
    pairing_secret: str
    expires_note: str = "Single-use; invalidated once consumed by /system/pair."


class PairRequest(BaseModel):
    pairing_secret: str
    extension_origin: str


class PairResponse(BaseModel):
    extension_token: str


class AutomationStatusResponse(BaseModel):
    mode: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(time=datetime.now(UTC).isoformat())


@router.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(
        backend_version=BACKEND_VERSION,
        api_version=API_VERSION,
        schema_version=SCHEMA_VERSION,
    )


@router.post("/system/pairing-secret", response_model=PairingSecretResponse)
def create_pairing_secret() -> PairingSecretResponse:
    """
    Called by the dashboard (not the extension) to display/relay a fresh
    pairing secret during first-run setup.
    """
    global _current_pairing_secret
    _current_pairing_secret = generate_pairing_secret()
    return PairingSecretResponse(pairing_secret=_current_pairing_secret)


@router.post("/system/pair", response_model=PairResponse)
def pair_extension(payload: PairRequest, db: Session = Depends(get_db)) -> PairResponse:
    global _current_pairing_secret
    if not _current_pairing_secret or payload.pairing_secret != _current_pairing_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired pairing secret")

    allowlist = settings.EXTENSION_ORIGIN_ALLOWLIST
    if allowlist and payload.extension_origin not in allowlist:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Extension origin not allowlisted")

    token = issue_extension_token(db, payload.extension_origin)
    _current_pairing_secret = None  # single-use
    return PairResponse(extension_token=token)


@router.get("/automation/status", response_model=AutomationStatusResponse)
def automation_status(db: Session = Depends(get_db)) -> AutomationStatusResponse:
    state = db.query(AutomationState).first()
    return AutomationStatusResponse(mode=state.mode if state else "PAUSED")
