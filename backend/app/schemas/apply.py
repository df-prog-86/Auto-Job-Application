"""Schemas for the extension's fill-an-application flow and the Needs Attention list."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApplyContextIn(BaseModel):
    url: str
    job_id: int | None = None


class CandidateFacts(BaseModel):
    first_name: str
    preferred_name: str | None = None
    recent_title: str | None = None
    recent_employer: str | None = None
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


class ApplyExperience(BaseModel):
    title: str
    employer: str
    location: str | None = None
    start_date: str | None = None  # "YYYY-MM"
    end_date: str | None = None  # "YYYY-MM"; None with current=True
    current: bool = False
    # The role's bullets from the resume being used for this job (tailored, else the original), one per line.
    description: str = ""


class ApplyEducation(BaseModel):
    institution: str
    degree: str | None = None
    field: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    gpa: str | None = None


class ApplyCertification(BaseModel):
    name: str
    issuer: str | None = None
    issued: str | None = None  # "YYYY-MM-DD"
    expires: str | None = None


class ApplyContextOut(BaseModel):
    job: ApplyJob | None = None
    candidate: CandidateFacts | None = None
    answers: dict[str, Any] = {}  # work_authorization, sponsorship_required, security_clearance
    learned_answers: dict[str, str] = {}  # normalized question -> the candidate's own saved answer
    resume: ApplyResume | None = None
    experience: list[ApplyExperience] = []
    education: list[ApplyEducation] = []
    certifications: list[ApplyCertification] = []
    skills: list[str] = []  # the candidate's skills, ones named in the job posting first
    # When the page didn't match a saved job: the saved jobs the user can pick from.
    candidates: list[ApplyJob] = []
    problem: str | None = None


class FlaggedField(BaseModel):
    label: str
    field_type: str = "text"
    options: list[str] = []
    required: bool = False


class LearnedAnswerIn(BaseModel):
    label: str
    value: str


class LearnedIn(BaseModel):
    """Answers the person typed or chose themselves on an application form."""

    answers: list[LearnedAnswerIn] = []
    job_id: int | None = None


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
