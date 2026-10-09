from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.discovery import JobOut


class JobSearchIn(BaseModel):
    """What to look for. Only these words are sent to the search; nothing from the profile is."""

    titles: str = Field(min_length=2, max_length=300)
    location: str | None = Field(default=None, max_length=200)
    work_type: Literal["any", "remote", "hybrid", "onsite"] = "any"
    exclude_companies: str | None = Field(default=None, max_length=300)  # comma separated
    keywords: str | None = Field(default=None, max_length=300)
    target_salary: int | None = Field(default=None, ge=0, le=2_000_000)  # midpoint of the pay range wanted
    require_salary: bool = False  # skip postings that do not state pay
    posted_within_days: Literal[0, 7, 14, 30] = 0  # 0 = any time
    count: int = Field(default=10, ge=3, le=15)
    # True for "Show more results": look only in the saved employer lists, which is instant and uses no AI.
    more: bool = False


class JobSearchResultOut(BaseModel):
    id: int
    title: str
    company: str
    location: str | None
    work_type: str | None
    salary_text: str | None
    posted_at: dt.date | None = None
    match_score: float | None = None
    match_summary: str | None = None
    match_gaps: list[str] | None = None
    match_from_page: bool | None = None
    summary: str | None
    url: str
    grounded: bool
    status: str

    class Config:
        from_attributes = True


class CoverageSystemOut(BaseModel):
    employers: int
    postings: int


class CoverageOut(BaseModel):
    """What the saved employer lists covered, shown above the results."""

    employers: int
    postings: int
    matches: int = 0  # postings in the saved lists that fit this search and were not already shown or saved
    matches_capped: bool = False  # True when there may be more than `matches`
    waiting: int = 0  # employers added but not read yet
    refreshing: bool = False
    by_system: dict[str, CoverageSystemOut] = {}


class JobSearchRunOut(BaseModel):
    found: int  # new results added by this search
    skipped: int  # already in your jobs, already shown, removed earlier, or not a real posting link
    results: list[JobSearchResultOut]
    coverage: CoverageOut | None = None
    more_available: int = 0  # further matches in the saved lists that were not shown this time
    more_capped: bool = False


class EmployerOut(BaseModel):
    id: int
    name: str
    system: str  # workday / greenhouse / lever / ashby
    enabled: bool
    status: str  # new / ok / error / unreachable
    open_jobs: int
    last_read: dt.datetime | None = None
    last_error: str | None = None
    source: str


class EmployersOut(BaseModel):
    employers: list[EmployerOut]
    total_employers: int
    total_postings: int
    refreshing: bool
    refresh_done: int = 0
    refresh_total: int = 0
    last_refresh: dt.datetime | None = None
    disabled_systems: list[str] = []


class AddEmployerIn(BaseModel):
    url: str = Field(min_length=8, max_length=1000)


class EnabledIn(BaseModel):
    enabled: bool


class AddResultOut(BaseModel):
    job: JobOut
    from_summary: bool  # True when the posting page could not be read and the search summary was used


class ClearOut(BaseModel):
    cleared: int
