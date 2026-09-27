"""API-facing schemas for the CandidateAnswer library (spec §13)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

ValueType = Literal["bool", "str", "number", "date"]

# Standard keys from spec §13. Not an enforced enum — a candidate/employer
# question that maps to a category not in this list should still be
# storable (spec §59 learns new mappings over time) — this list exists for
# the UI to render sensible defaults, not to gate what can be saved.
STANDARD_ANSWER_KEYS = [
    "work_authorization",
    "sponsorship_required",
    "relocation",
    "start_date",
    "salary_minimum",
    "salary_target",
    "travel_percentage",
    "security_clearance",
]


class AnswerUpsertRequest(BaseModel):
    value_type: ValueType
    value: Any
    explanatory_text: str | None = None
    user_confirmed: bool = True


class AnswerOut(BaseModel):
    answer_key: str
    value_type: str
    value: Any
    explanatory_text: str | None
    provenance: str | None
    user_confirmed: bool

    class Config:
        from_attributes = True


class ExperienceSummaryEntry(BaseModel):
    skill: str
    total_years: float
    claim_count: int
    has_unknown_dates: bool


class ExperienceSummaryResponse(BaseModel):
    entries: list[ExperienceSummaryEntry]
