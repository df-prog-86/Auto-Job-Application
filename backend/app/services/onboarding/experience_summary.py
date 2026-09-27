"""
Per-skill total-experience summary, built from VerifiedClaims using the
deterministic calculator in experience_calculator.py — never an LLM guess
(spec §13, §56: "years of experience" must not be generatively invented).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.candidate import VerifiedClaim
from app.schemas.answers import ExperienceSummaryEntry, ExperienceSummaryResponse
from app.services.onboarding.experience_calculator import DateInterval, total_experience_years


def compute_experience_summary(db: Session, profile_id: int) -> ExperienceSummaryResponse:
    claims = db.query(VerifiedClaim).filter(VerifiedClaim.profile_id == profile_id).all()

    by_skill: dict[str, list[VerifiedClaim]] = {}
    for claim in claims:
        for skill in claim.skills:
            by_skill.setdefault(skill, []).append(claim)

    entries: list[ExperienceSummaryEntry] = []
    for skill, skill_claims in sorted(by_skill.items()):
        intervals: list[DateInterval] = []
        has_unknown_dates = False

        for claim in skill_claims:
            if claim.start_date is None:
                has_unknown_dates = True  # this claim supports the skill but can't contribute duration
                continue
            intervals.append(DateInterval(start=claim.start_date, end=claim.end_date))

        entries.append(
            ExperienceSummaryEntry(
                skill=skill,
                total_years=round(total_experience_years(intervals), 2) if intervals else 0.0,
                claim_count=len(skill_claims),
                has_unknown_dates=has_unknown_dates,
            )
        )

    return ExperienceSummaryResponse(entries=entries)
