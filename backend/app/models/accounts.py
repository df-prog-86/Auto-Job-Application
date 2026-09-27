from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class CandidateAccount(Base, TimestampMixin):
    """
    One candidate account per ATS tenant (spec §44/§45). Passwords are NEVER
    stored here — `credential_reference` is a keyring lookup key, resolved
    only by the credentials service, only for the extension-only endpoint.
    """

    __tablename__ = "candidate_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employer: Mapped[str] = mapped_column(String(300))
    ats: Mapped[str] = mapped_column(String(50), index=True)
    tenant_key: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    career_site_origin: Mapped[str] = mapped_column(String(300))
    username: Mapped[str] = mapped_column(String(320))
    credential_reference: Mapped[str] = mapped_column(String(200))
    account_status: Mapped[str] = mapped_column(String(30), default="pending")
    # pending/connected/verification_required/locked/recovery_needed
    date_created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    last_successful_login: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
