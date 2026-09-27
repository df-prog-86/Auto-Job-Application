from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class QuestionMapping(Base, TimestampMixin):
    """Known question -> canonical answer category (spec §59)."""

    __tablename__ = "question_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_question: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(50))
    success_count: Mapped[int] = mapped_column(Integer, default=0)


class FieldMapping(Base, TimestampMixin):
    """Successful DOM field -> candidate field mappings by ATS (spec §9)."""

    __tablename__ = "field_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ats: Mapped[str] = mapped_column(String(50), index=True)
    normalized_label: Mapped[str] = mapped_column(String(300))
    dom_signature: Mapped[str] = mapped_column(String(500))
    canonical_field: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    last_validated_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
