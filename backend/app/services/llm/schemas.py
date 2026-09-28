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


class ExtractedRequirement(BaseModel):
    """One requirement pulled from a job description (spec §21 Stage 2) --
    every requirement must carry required-vs-preferred, a confidence, and
    the exact text it came from, never just a bare string."""

    text: str = Field(description="Normalized requirement, e.g. '5+ years Python'")
    requirement_type: str = Field(
        description="One of: skill, education, certification, domain_experience, "
        "years_experience, travel, other"
    )
    is_required: bool
    confidence: float = Field(ge=0.0, le=1.0)
    source_text: str = Field(description="Verbatim text from the job description this was extracted from")


class JobRequirementsExtraction(BaseModel):
    """Stage 2 of the qualification pipeline (spec §21): structured
    requirements extracted from a job description by the cheap model, after
    Stage 1's free deterministic hard-constraint checks have already run."""

    normalized_title: str | None = None
    seniority: str | None = None
    required_years: float | None = None
    employment_type: str | None = None
    remote_policy: str | None = None
    work_authorization_note: str | None = None
    sponsorship_offered: bool | None = None
    clearance_required: str | None = None
    travel_requirement: str | None = None
    requirements: list[ExtractedRequirement] = Field(default_factory=list)


class JobPostingExtraction(BaseModel):
    """
    Fallback shape for manual job intake (services/discovery/manual_extraction.py)
    when a page has no schema.org JobPosting structured data to read
    deterministically. Only used as a last resort, per spec §7's
    deterministic-before-generative principle.

    is_job_posting is required and checked BEFORE any other field is
    trusted: title/company/description are optional so the model has a
    real way to say "this page isn't a job posting" instead of being forced
    to invent a plausible-looking title and company for, say, a news
    article or a company's About page.
    """

    is_job_posting: bool = Field(
        description="False if the page text clearly is not a single job posting "
        "(e.g. a news article, a company's About page, a search results page). "
        "When False, leave the other fields null rather than guessing."
    )
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = Field(
        default=None,
        description="The job description/responsibilities/requirements text, "
        "verbatim from the source page -- do not summarize or paraphrase it.",
    )
    salary_text: str | None = None
