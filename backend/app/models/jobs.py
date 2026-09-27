from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin


class Job(Base, TimestampMixin):
    """
    One canonical job posting (spec §9 Jobs, §19-20). Deduplicated by
    (ats, external_job_id) first, then canonical URL, then a SHA-256 of
    normalized (company, title, location) — never Python's runtime hash().
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_job_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    ats: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    external_job_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company: Mapped[str] = mapped_column(String(300))
    normalized_company: Mapped[str] = mapped_column(String(300), index=True)
    title: Mapped[str] = mapped_column(String(300))
    normalized_title: Mapped[str] = mapped_column(String(300), index=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    remote_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    salary: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_application_url: Mapped[str] = mapped_column(String(1000))
    first_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="open")  # open/closed/unknown

    sources: Mapped[list["JobSource"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    requirements: Mapped[list["JobRequirement"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    evaluations: Mapped[list["JobEvaluation"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobSource(Base, TimestampMixin):
    """Multiple discovery sources can point at the same Job (spec §20)."""

    __tablename__ = "job_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[str] = mapped_column(String(1000))
    discovered_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    external_source_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    job: Mapped[Job] = relationship(back_populates="sources")


class JobRequirement(Base, TimestampMixin):
    """Each extracted requirement, stored separately (spec §21 Stage 2)."""

    __tablename__ = "job_requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    requirement_type: Mapped[str] = mapped_column(String(50))
    normalized_requirement: Mapped[str] = mapped_column(String(500))
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)  # False = preferred
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    job: Mapped[Job] = relationship(back_populates="requirements")


class JobEvaluation(Base, TimestampMixin):
    """Qualification pipeline output for a (job, profile) pair (spec §23)."""

    __tablename__ = "job_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    hard_filter_result: Mapped[str] = mapped_column(String(20))  # PASS/FAIL/UNKNOWN
    required_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    preferred_score: Mapped[float] = mapped_column(Float, default=0.0)
    domain_alignment: Mapped[float] = mapped_column(Float, default=0.0)
    seniority_alignment: Mapped[float] = mapped_column(Float, default=0.0)
    preference_alignment: Mapped[float] = mapped_column(Float, default=0.0)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    disqualifiers: Mapped[list[str]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[str]] = mapped_column(JSON, default=list)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evaluation_version: Mapped[str] = mapped_column(String(20), default="1")

    job: Mapped[Job] = relationship(back_populates="evaluations")
