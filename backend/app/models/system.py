from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class ExtensionPairing(Base, TimestampMixin):
    """
    Persistent local auth token issued to the Chrome extension after
    pairing (spec §8.3). Only one active pairing is expected in normal
    single-user local use, but the table allows re-pairing without losing
    history (old rows are revoked, not deleted).
    """

    __tablename__ = "extension_pairings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    extension_origin: Mapped[str] = mapped_column(String(200))
    paired_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutomationState(Base, TimestampMixin):
    """Singleton row holding the global automation mode (spec §79)."""

    __tablename__ = "automation_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), default="PAUSED")  # PAUSED/REVIEW/AUTO
