"""
Candidate data: profile, resume-derived history, and the two answer tables
that are kept deliberately separate per spec §8.4/§60 — CandidateAnswer for
ordinary application answers, VoluntaryDisclosure for demographic/EEO data
that must never influence qualification, scoring, or resume generation and
is never inferred, only explicitly supplied.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin


class CandidateProfile(Base, TimestampMixin):
    __tablename__ = "candidate_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    preferred_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    portfolio_urls: Mapped[list[str]] = mapped_column(JSON, default=list)

    employment_history: Mapped[list["EmploymentHistory"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    education: Mapped[list["Education"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    skills: Mapped[list["Skill"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    certifications: Mapped[list["Certification"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class EmploymentHistory(Base, TimestampMixin):
    __tablename__ = "employment_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    employer: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(300))
    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)  # null = current
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_resume_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    profile: Mapped[CandidateProfile] = relationship(back_populates="employment_history")


class Education(Base, TimestampMixin):
    __tablename__ = "education"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    institution: Mapped[str] = mapped_column(String(300))
    degree: Mapped[str | None] = mapped_column(String(200), nullable=True)
    field: Mapped[str | None] = mapped_column(String(200), nullable=True)
    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)

    profile: Mapped[CandidateProfile] = relationship(back_populates="education")


class Skill(Base, TimestampMixin):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    canonical_skill: Mapped[str] = mapped_column(String(200), index=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    candidate_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)

    profile: Mapped[CandidateProfile] = relationship(back_populates="skills")


class Certification(Base, TimestampMixin):
    __tablename__ = "certifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    certification: Mapped[str] = mapped_column(String(300))
    issuer: Mapped[str | None] = mapped_column(String(300), nullable=True)
    date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    expiration: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)

    profile: Mapped[CandidateProfile] = relationship(back_populates="certifications")


class VerifiedClaim(Base, TimestampMixin):
    """
    Atomic, source-traceable candidate facts (spec §12). This table is the
    single source of truth any generative step (resume tailoring, answer
    generation) is allowed to draw factual content from.
    """

    __tablename__ = "verified_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(50), index=True)  # experience/education/skill/...
    canonical_text: Mapped[str] = mapped_column(Text)
    employer: Mapped[str | None] = mapped_column(String(300), nullable=True)
    associated_role: Mapped[str | None] = mapped_column(String(300), nullable=True)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    source_document: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_section: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)


class CandidateAnswer(Base, TimestampMixin):
    """
    Canonical deterministic application answers (spec §13): work
    authorization, sponsorship, relocation, salary, etc. Distinct from
    VoluntaryDisclosure — these are ordinary application facts, not
    protected/demographic data.
    """

    __tablename__ = "candidate_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    answer_key: Mapped[str] = mapped_column(String(100), index=True)  # e.g. "work_authorization"
    value_type: Mapped[str] = mapped_column(String(20))  # bool/str/number/date
    value: Mapped[dict] = mapped_column(JSON)  # {"raw": ...}
    explanatory_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class VoluntaryDisclosure(Base, TimestampMixin):
    """
    Separate table, per spec §8.4/§60: only explicit candidate responses to
    voluntary/EEO-style questions are ever stored here, never inferred.
    Never joined into qualification, scoring, or resume-generation queries.
    """

    __tablename__ = "voluntary_disclosures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    disclosure_key: Mapped[str] = mapped_column(String(100))  # e.g. "gender", "veteran_status"
    response_mode: Mapped[str] = mapped_column(String(20))  # explicit/prefer_not_to_answer/ask_each_time
    value: Mapped[str | None] = mapped_column(String(200), nullable=True)
