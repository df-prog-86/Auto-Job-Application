from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.discovery import JobOut


class JobSearchIn(BaseModel):
    """What to look for. Only these words are sent to the search; nothing from the profile is."""

    titles: str = Field(min_length=2, max_length=300)
    location: str | None = Field(default=None, max_length=200)
    work_type: Literal["any", "remote", "hybrid", "onsite"] = "any"
    keywords: str | None = Field(default=None, max_length=300)
    target_salary: int | None = Field(default=None, ge=0, le=2_000_000)  # midpoint of the pay range wanted
    require_salary: bool = False  # skip postings that do not state pay
    posted_within_days: Literal[0, 7, 14, 30] = 0  # 0 = any time
    count: int = Field(default=10, ge=3, le=15)


class JobSearchResultOut(BaseModel):
    id: int
    title: str
    company: str
    location: str | None
    work_type: str | None
    salary_text: str | None
    summary: str | None
    url: str
    grounded: bool
    status: str

    class Config:
        from_attributes = True


class JobSearchRunOut(BaseModel):
    found: int  # new results added by this search
    skipped: int  # already in your jobs, already shown, removed earlier, or not a real posting link
    results: list[JobSearchResultOut]


class AddResultOut(BaseModel):
    job: JobOut
    from_summary: bool  # True when the posting page could not be read and the search summary was used


class ClearOut(BaseModel):
    cleared: int
