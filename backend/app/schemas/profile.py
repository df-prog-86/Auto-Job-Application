"""API-facing Pydantic schemas for the profile/onboarding endpoints."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel

from app.services.llm.schemas import ResumeExtraction


class ResumeParseResponse(BaseModel):
    """
    Result of POST /resume/parse: the raw extracted text, the LLM's
    structured extraction, and the draft claims generated from it — all
    for the candidate to review/correct (spec §10, §12) before anything is
    committed. Nothing here has touched the database yet.
    """

    extracted_text_preview: str  # first N chars, so the UI can show "here's what we read"
    used_ocr: bool
    extraction: ResumeExtraction
    draft_claims: list["DraftClaimOut"]


class DraftClaimOut(BaseModel):
    category: str
    canonical_text: str
    employer: str | None = None
    associated_role: str | None = None
    skills: list[str] = []
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    metrics: dict = {}
    source_section: str
    source_text: str


class CommitProfileRequest(BaseModel):
    """
    What the candidate actually confirmed, after reviewing/correcting the
    parse result — this, not the raw LLM output, is what gets committed.
    """

    extraction: ResumeExtraction
    approved_claims: list[DraftClaimOut]
    resume_filename: str


class EmploymentHistoryOut(BaseModel):
    id: int
    employer: str
    title: str
    start_date: dt.date | None
    end_date: dt.date | None
    location: str | None

    class Config:
        from_attributes = True


class EducationOut(BaseModel):
    id: int
    institution: str
    degree: str | None
    field: str | None
    start_date: dt.date | None
    end_date: dt.date | None
    gpa: str | None = None

    class Config:
        from_attributes = True


class SkillOut(BaseModel):
    id: int
    canonical_skill: str
    candidate_confirmed: bool

    class Config:
        from_attributes = True


class CertificationOut(BaseModel):
    id: int
    certification: str
    issuer: str | None
    date: dt.date | None
    expiration: dt.date | None

    class Config:
        from_attributes = True


class VerifiedClaimSummaryOut(BaseModel):
    category: str
    canonical_text: str

    class Config:
        from_attributes = True


class ProfileOut(BaseModel):
    id: int
    name: str
    preferred_name: str | None
    email: str
    phone: str | None
    location: str | None
    linkedin_url: str | None
    portfolio_urls: list[str]
    employment_history: list[EmploymentHistoryOut] = []
    education: list[EducationOut] = []
    skills: list[SkillOut] = []
    certifications: list[CertificationOut] = []
    verified_claims: list[VerifiedClaimSummaryOut] = []

    class Config:
        from_attributes = True


class ProfileUpdateRequest(BaseModel):
    name: str | None = None
    preferred_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    portfolio_urls: list[str] | None = None


class EmploymentIn(BaseModel):
    """Dates are "YYYY-MM" (or "YYYY-MM-DD"); an empty end date means current."""

    employer: str | None = None
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    location: str | None = None


class EducationIn(BaseModel):
    institution: str | None = None
    degree: str | None = None
    field: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    gpa: str | None = None


class CertificationIn(BaseModel):
    certification: str | None = None
    issuer: str | None = None
    date: str | None = None
    expiration: str | None = None


class SkillIn(BaseModel):
    canonical_skill: str


class MasterRoleOut(BaseModel):
    """One role's bullets, read from the saved master Word resume (read-only)."""

    context: str
    bullets: list[str]


ResumeParseResponse.model_rebuild()
