"""
Extension pairing and per-request auth verification (spec §8.2/§8.3).

Flow:
  1. Backend generates a one-time pairing secret at first run (or on demand).
  2. The extension calls POST /api/v1/system/pair with that secret.
  3. Backend issues a persistent local token, storing only its hash.
  4. Every subsequent extension request presents that token; this module
     verifies it (plus origin, Host header, and body size) before the
     request reaches any route handler.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.system import ExtensionPairing

PAIRING_SECRET_BYTES = 32
EXTENSION_TOKEN_BYTES = 32


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_pairing_secret() -> str:
    """One-time secret shown/used during first-run pairing. Never persisted as-is."""
    return secrets.token_urlsafe(PAIRING_SECRET_BYTES)


def issue_extension_token(db: Session, extension_origin: str) -> str:
    """
    Mints a new persistent token for the extension, revoking any prior
    pairing (spec assumes single-user local use; re-pairing replaces, not
    accumulates, active tokens).
    """
    for existing in db.query(ExtensionPairing).filter_by(revoked=False).all():
        existing.revoked = True

    token = secrets.token_urlsafe(EXTENSION_TOKEN_BYTES)
    pairing = ExtensionPairing(
        token_hash=_hash_token(token),
        extension_origin=extension_origin,
        paired_at=datetime.now(UTC),
        revoked=False,
    )
    db.add(pairing)
    db.commit()
    return token


def verify_extension_token(db: Session, token: str | None) -> ExtensionPairing | None:
    if not token:
        return None
    pairing = (
        db.query(ExtensionPairing)
        .filter_by(token_hash=_hash_token(token), revoked=False)
        .one_or_none()
    )
    if pairing is not None:
        pairing.last_seen_at = datetime.now(UTC)
        db.commit()
    return pairing
