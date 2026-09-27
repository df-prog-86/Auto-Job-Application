from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin


class ApplicationState(str, enum.Enum):
    """Spec §30 — every transition must create an ApplicationEvent."""

    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    OPENING = "OPENING"
    ATS_DETECTED = "ATS_DETECTED"
    ACCOUNT_CHECK = "ACCOUNT_CHECK"
    AUTHENTICATING = "AUTHENTICATING"
    FILLING = "FILLING"
    VALIDATING = "VALIDATING"
    AWAITING_EXTERNAL_ACTION = "AWAITING_EXTERNAL_ACTION"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    SUBMISSION_UNVERIFIED = "SUBMISSION_UNVERIFIED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"


class Application(Base, TimestampMixin):
    """One row per actual application attempt (spec §9 Applications)."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    current_state: Mapped[str] = mapped_column(String(30), default=ApplicationState.QUEUED.value)
    submission_mode: Mapped[str] = mapped_column(String(20), default="review")  # review/auto
    adapter: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adapter_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    queued_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    lease_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    lease_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(100), nullable=True)  # error code, spec §31

    resume_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("generated_documents.id"), nullable=True
    )
    confirmation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    final_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="ApplicationEvent.id"
    )
    answers: Mapped[list["ApplicationAnswer"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class ApplicationEvent(Base):
    """Append-only event history (spec §9 ApplicationEvents). No update mixin — never mutated."""

    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(50))
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)  # sanitized only — never secrets
    adapter_state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    application: Mapped[Application] = relationship(back_populates="events")


class ApplicationAnswer(Base, TimestampMixin):
    """Spec §9 ApplicationAnswers."""

    __tablename__ = "application_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    normalized_question: Mapped[str | None] = mapped_column(String(500), nullable=True)
    answer_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    answer_submitted: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(30))  # mapping/deterministic/generated/manual
    claim_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_approved: Mapped[bool] = mapped_column(default=False)

    application: Mapped[Application] = relationship(back_populates="answers")
