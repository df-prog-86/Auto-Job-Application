from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class GeneratedDocument(Base, TimestampMixin):
    """Tailored resumes/cover letters produced for a specific job (spec §9)."""

    __tablename__ = "generated_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    document_type: Mapped[str] = mapped_column(String(30))  # resume/cover_letter
    local_path: Mapped[str] = mapped_column(String(1000))
    format: Mapped[str] = mapped_column(String(10))  # pdf/docx
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    template_version: Mapped[str] = mapped_column(String(20))
    source_claim_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    content_hash: Mapped[str] = mapped_column(String(64))
