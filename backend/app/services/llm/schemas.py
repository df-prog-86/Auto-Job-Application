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


class PlannedBullet(BaseModel):
    bullet_id: int
    text: str = Field(
        description="The bullet's text. Identical to the original unless a tiny truthful "
        "swap or light job-language lead-in is made."
    )


class PlannedBlock(BaseModel):
    block_id: int
    bullets: list[PlannedBullet] = Field(
        default_factory=list,
        description="Every bullet of this block exactly once, best fit to the job first.",
    )


class TailorPlan(BaseModel):
    """
    What the model decides for a tailored resume (spec §25-26, adapted): the
    order of each role's bullets and any tiny wording changes. It never
    touches layout, headings, dates, employers, or sections. The edits are
    applied to a copy of the candidate's own master Word file.
    """

    blocks: list[PlannedBlock] = Field(default_factory=list)
    changelog: list[str] = Field(
        default_factory=list,
        description="Plain notes for the candidate: what was reordered or lightly reworded, "
        "and every job requirement the master resume does not support (missing tools, "
        "certifications, years under the bar). Gaps are only noted here, never papered over.",
    )


class ResumeJobMatchResult(BaseModel):
    """
    Simple, direct resume-vs-job comparison (Milestone 4, simplified per
    product direction: "just compare my resume to the job posting").
    Replaces the earlier multi-stage pipeline (hard constraints, separate
    requirement extraction, deterministic evidence matching, weighted
    scoring) with one LLM call that reads the candidate's own background
    and the job description and judges the fit directly.
    """

    match_percentage: int = Field(
        ge=0, le=100, description="Overall fit between the resume and the job, 0-100"
    )
    summary: str = Field(
        max_length=700,
        description="One or two plain-language sentences explaining the score -- "
        "what fits well and what's missing. Written for the candidate to read directly."
    )
    gaps: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Short list of specific, concrete qualifications/skills/experience "
        "the job asks for that don't show up in the resume. Empty if there aren't any. "
        "Never vague -- e.g. '5+ years of Python' not 'more experience'.",
    )


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
