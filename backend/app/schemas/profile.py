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


class ProfileOut(BaseModel):
    id: int
    name: str
    preferred_name: str | None
    email: str
    phone: str | None
    location: str | None
    linkedin_url: str | None
    portfolio_urls: list[str]

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


ResumeParseResponse.model_rebuild()
