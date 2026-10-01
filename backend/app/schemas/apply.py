"""Schemas for the extension's fill-an-application flow and the Needs Attention list."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApplyContextIn(BaseModel):
    url: str
    job_id: int | None = None


class CandidateFacts(BaseModel):
    first_name: str
    last_name: str
    full_name: str
    email: str
    phone: str | None
    location: str | None
    linkedin_url: str | None


class ApplyJob(BaseModel):
    id: int
    title: str
    company: str
    url: str
    proceeding: bool


class ApplyResume(BaseModel):
    document_id: int
    filename: str
    format: str


class ApplyContextOut(BaseModel):
    job: ApplyJob | None = None
    candidate: CandidateFacts | None = None
    answers: dict[str, Any] = {}  # work_authorization, sponsorship_required, security_clearance
    learned_answers: dict[str, str] = {}  # normalized question -> the candidate's own saved answer
    resume: ApplyResume | None = None
    # When the page didn't match a saved job: the saved jobs the user can pick from.
    candidates: list[ApplyJob] = []
    problem: str | None = None


class FlaggedField(BaseModel):
    label: str
    field_type: str = "text"
    options: list[str] = []
    required: bool = False


class ApplyReportIn(BaseModel):
    job_id: int
    page_url: str | None = None
    filled_count: int = 0
    flagged: list[FlaggedField] = []


class PendingQuestionOut(BaseModel):
    id: int
    job_id: int
    job_title: str
    company: str
    label: str
    field_type: str
    options: list[str]
    required: bool
    status: str
    answer_text: str | None = None

    class Config:
        from_attributes = True


class AnswerQuestionIn(BaseModel):
    answer: str
