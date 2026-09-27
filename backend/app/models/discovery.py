"""
Employer watchlist for ATS-based discovery (spec §16-17).

Greenhouse and Lever have no public "search every job everywhere" API — each
employer's postings live at that employer's own board. Discovery therefore
works by iterating a list of employers the candidate has chosen to watch,
rather than free-text search across the whole internet. This model is that
watchlist; it doesn't appear verbatim in the spec, which doesn't resolve how
targets are chosen, so this is the resolution.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class TargetEmployer(Base, TimestampMixin):
    """
    One employer to poll during discovery. `identifier` is the ATS-specific
    slug: the Greenhouse board token (from boards.greenhouse.io/<token>) or
    the Lever company slug (from jobs.lever.co/<slug>).
    """

    __tablename__ = "target_employers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    ats: Mapped[str] = mapped_column(String(50), index=True)  # "greenhouse" | "lever"
    identifier: Mapped[str] = mapped_column(String(200))  # board token / company slug
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_status: Mapped[str | None] = mapped_column(String(30), nullable=True)  # ok/error
    last_check_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
