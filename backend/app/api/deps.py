"""Shared FastAPI dependencies for the API layer."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.system import ExtensionPairing
from app.services.security.pairing import verify_extension_token

__all__ = ["get_db", "require_extension_auth"]


def require_extension_auth(
    x_extension_token: str | None = Header(default=None, alias="X-Extension-Token"),
    db: Session = Depends(get_db),
) -> ExtensionPairing:
    """
    Route dependency guarding every extension-only endpoint (credential
    retrieval, application claiming, etc. — spec §8.2, §75).
    """
    pairing = verify_extension_token(db, x_extension_token)
    if pairing is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing extension token")
    return pairing
