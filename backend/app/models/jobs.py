from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text
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
    posted_at: Mapped[dt.date | None] = mapped_column(Date, nullable=True)  # when the employer posted it, if known
    first_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="open")  # open/closed/unknown
    # Whether the candidate has told the system to move forward with an
    # application -- deliberately separate from qualification scoring, which
    # runs automatically. Nothing past this stays "not_started" without the
    # candidate explicitly clicking "Proceed with Application" (spec-adjacent
    # design decision: ranking is automatic, acting on a rank never is).
    application_status: Mapped[str] = mapped_column(String(30), default="not_started")

    sources: Mapped[list["JobSource"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    evaluations: Mapped[list["JobEvaluation"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    documents: Mapped[list["GeneratedDocument"]] = relationship(  # noqa: F821
        "GeneratedDocument", cascade="all, delete-orphan", passive_deletes=True
    )
    pending_questions: Mapped[list["PendingQuestion"]] = relationship(  # noqa: F821
        "PendingQuestion", cascade="all, delete-orphan"
    )

    @property
    def evaluation(self) -> "JobEvaluation | None":
        """Convenience accessor for the API layer: the qualification
        pipeline (services/qualification/pipeline.py) upserts at most one
        JobEvaluation per job, so there's normally exactly one row here."""
        return self.evaluations[0] if self.evaluations else None


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


class JobEvaluation(Base, TimestampMixin):
    """
    Qualification result for a (job, profile) pair -- a single, direct
    resume-vs-job-posting comparison (Milestone 4, simplified): one overall
    score, a plain-language summary of why, and a short list of concrete
    gaps. Replaces the earlier multi-component weighted score.
    """

    __tablename__ = "job_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str] = mapped_column(Text, default="")
    gaps: Mapped[list[str]] = mapped_column(JSON, default=list)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evaluation_version: Mapped[str] = mapped_column(String(20), default="1")

    job: Mapped[Job] = relationship(back_populates="evaluations")
