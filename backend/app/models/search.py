from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class SearchProfile(Base, TimestampMixin):
    """A named job-search configuration (spec §9 SearchProfiles / §4.3)."""

    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    remote: Mapped[bool] = mapped_column(Boolean, default=True)
    hybrid: Mapped[bool] = mapped_column(Boolean, default=True)
    onsite: Mapped[bool] = mapped_column(Boolean, default=False)
    salary_minimum: Mapped[float | None] = mapped_column(Float, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    desired_seniority: Mapped[list[str]] = mapped_column(JSON, default=list)
    excluded_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    excluded_employers: Mapped[list[str]] = mapped_column(JSON, default=list)
    excluded_industries: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    travel_preference: Mapped[str | None] = mapped_column(String(50), nullable=True)
    relocation_willingness: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
