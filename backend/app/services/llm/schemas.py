"""
Structured extraction schemas the LLM must return (spec §11). Pydantic
validates shape; it is explicitly *not* sufficient enforcement on its own
(spec §11: "Do not treat Pydantic alone as model-output enforcement") — the
router pairs this with the provider's own structured-output/JSON-schema mode
and a bounded retry-then-fallback policy (app/services/llm/router.py).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ContactInfo(BaseModel):
    name: str
    preferred_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    portfolio_urls: list[str] = Field(default_factory=list)


class EmploymentEntry(BaseModel):
    employer: str
    title: str
    start_date: str | None = None  # ISO "YYYY-MM" or "YYYY-MM-DD"; parsed/validated downstream
    end_date: str | None = None  # None = current role
    location: str | None = None
    source_text: str = Field(description="Verbatim bullet/paragraph this entry was extracted from")


class EducationEntry(BaseModel):
    institution: str
    degree: str | None = None
    field: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class CertificationEntry(BaseModel):
    certification: str
    issuer: str | None = None
    date: str | None = None
    expiration: str | None = None


class ProjectEntry(BaseModel):
    name: str
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)
    source_text: str | None = None


class ResumeExtraction(BaseModel):
    """The minimum shape required by spec §11."""

    contact: ContactInfo
    employment: list[EmploymentEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
