"""API-facing schemas for search profiles, the employer watchlist, jobs, and discovery runs."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class SearchProfileIn(BaseModel):
    name: str
    titles: list[str] = []
    locations: list[str] = []
    remote: bool = True
    hybrid: bool = True
    onsite: bool = False
    salary_minimum: float | None = None
    employment_type: str | None = None
    desired_seniority: list[str] = []
    excluded_titles: list[str] = []
    excluded_employers: list[str] = []
    excluded_industries: list[str] = []
    required_keywords: list[str] = []
    preferred_keywords: list[str] = []
    travel_preference: str | None = None
    relocation_willingness: bool = False
    enabled: bool = True


class SearchProfileUpdate(BaseModel):
    name: str | None = None
    titles: list[str] | None = None
    locations: list[str] | None = None
    remote: bool | None = None
    hybrid: bool | None = None
    onsite: bool | None = None
    salary_minimum: float | None = None
    employment_type: str | None = None
    desired_seniority: list[str] | None = None
    excluded_titles: list[str] | None = None
    excluded_employers: list[str] | None = None
    excluded_industries: list[str] | None = None
    required_keywords: list[str] | None = None
    preferred_keywords: list[str] | None = None
    travel_preference: str | None = None
    relocation_willingness: bool | None = None
    enabled: bool | None = None


class SearchProfileOut(SearchProfileIn):
    id: int

    class Config:
        from_attributes = True


class TargetEmployerIn(BaseModel):
    name: str
    ats: str  # "greenhouse" | "lever"
    identifier: str
    enabled: bool = True
    notes: str | None = None


class TargetEmployerOut(TargetEmployerIn):
    id: int
    last_checked_at: dt.datetime | None = None
    last_check_status: str | None = None
    last_check_error: str | None = None

    class Config:
        from_attributes = True


class JobEvaluationOut(BaseModel):
    """Qualification pipeline output (spec §23) -- every component score is
    included, not just the overall one, so the UI can show *why* a job
    scored the way it did."""

    hard_filter_result: str
    required_coverage: float
    preferred_score: float
    domain_alignment: float
    seniority_alignment: float
    preference_alignment: float
    overall_score: float
    disqualifiers: list[str]
    gaps: list[str]
    model_used: str | None
    evaluation_version: str

    class Config:
        from_attributes = True


class JobOut(BaseModel):
    id: int
    ats: str | None
    company: str
    title: str
    location: str | None
    remote_type: str | None
    salary: dict
    canonical_application_url: str
    first_seen: dt.datetime
    last_seen: dt.datetime
    status: str
    application_status: str
    evaluation: JobEvaluationOut | None = None

    class Config:
        from_attributes = True


class JobDetailOut(JobOut):
    description: str | None

    class Config:
        from_attributes = True


class ManualJobIn(BaseModel):
    """Option 1: the user pastes a job posting URL for the backend to fetch itself."""

    url: str


class CaptureJobIn(BaseModel):
    """
    Option 2: the browser extension has already read the page the user is
    looking at (from their own logged-in session) and hands us its content
    directly instead of us fetching it -- json_ld is whatever
    <script type="application/ld+json"> blocks were on the page, body_text
    is the page's visible text, both read client-side so no markup/scripts
    are sent over.
    """

    url: str
    page_title: str | None = None
    json_ld: list[str] = []
    body_text: str = ""


class DiscoveryRunOut(BaseModel):
    employers_checked: int
    employers_failed: int
    postings_fetched: int
    postings_matched: int
    jobs_created: int
    jobs_updated: int
    errors: list[str]
