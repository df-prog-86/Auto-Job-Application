"""
Stage 3 of the qualification pipeline (spec §22): deterministic comparison
of each extracted requirement against the candidate's own verified profile
data. Spec allows embeddings only to *assist retrieval*, never to decide
qualification -- there's no embedding infrastructure wired in yet, so this
is plain, transparent keyword/text matching, which is more than adequate
for the number of requirements one job posting produces.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from app.models.candidate import CandidateProfile
from app.models.jobs import JobRequirement
from app.services.onboarding.experience_calculator import DateInterval, total_experience_years

MatchStatus = str  # "MET" | "PARTIALLY_MET" | "NOT_MET" | "UNKNOWN"

_YEARS_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")


@dataclass
class RequirementMatch:
    requirement: JobRequirement
    status: MatchStatus
    evidence: str | None = None


def _candidate_skill_texts(profile: CandidateProfile) -> list[str]:
    texts: list[str] = []
    for skill in profile.skills:
        texts.append(skill.canonical_skill.lower())
        texts.extend(a.lower() for a in skill.aliases)
    for claim in profile.verified_claims:
        texts.extend(s.lower() for s in claim.skills)
    return texts


def _contains(haystack_texts: list[str], needle: str) -> bool:
    needle = needle.lower().strip()
    if not needle:
        return False
    return any(needle in text or (text and text in needle) for text in haystack_texts if text)


def _match_skill(requirement: JobRequirement, profile: CandidateProfile) -> RequirementMatch:
    if _contains(_candidate_skill_texts(profile), requirement.normalized_requirement):
        return RequirementMatch(requirement, "MET", "Found in your skills or verified claims")

    claim_texts = [c.canonical_text.lower() for c in profile.verified_claims]
    if _contains(claim_texts, requirement.normalized_requirement):
        return RequirementMatch(
            requirement, "PARTIALLY_MET", "Mentioned in a verified claim, but not tagged as a skill"
        )
    return RequirementMatch(requirement, "NOT_MET", None)


def _match_education(requirement: JobRequirement, profile: CandidateProfile) -> RequirementMatch:
    education_texts = [f"{e.degree or ''} {e.field or ''}".lower() for e in profile.education]
    if _contains(education_texts, requirement.normalized_requirement):
        return RequirementMatch(requirement, "MET", "Matches your education history")
    return RequirementMatch(requirement, "NOT_MET" if requirement.is_required else "UNKNOWN", None)


def _match_certification(requirement: JobRequirement, profile: CandidateProfile) -> RequirementMatch:
    cert_texts = [c.certification.lower() for c in profile.certifications]
    if _contains(cert_texts, requirement.normalized_requirement):
        return RequirementMatch(requirement, "MET", "Matches a certification on file")
    return RequirementMatch(requirement, "NOT_MET" if requirement.is_required else "UNKNOWN", None)


def _match_domain_experience(requirement: JobRequirement, profile: CandidateProfile) -> RequirementMatch:
    haystack = [
        f"{c.employer or ''} {c.associated_role or ''} {c.canonical_text}".lower()
        for c in profile.verified_claims
    ]
    if _contains(haystack, requirement.normalized_requirement):
        return RequirementMatch(requirement, "MET", "Matches your work history")
    return RequirementMatch(requirement, "NOT_MET" if requirement.is_required else "PARTIALLY_MET", None)


def _match_years_experience(requirement: JobRequirement, profile: CandidateProfile) -> RequirementMatch:
    match = _YEARS_PATTERN.search(requirement.normalized_requirement)
    if not match:
        return RequirementMatch(requirement, "UNKNOWN", None)
    required_years = float(match.group(1))

    intervals = [
        DateInterval(start=e.start_date, end=e.end_date)
        for e in profile.employment_history
        if e.start_date is not None
    ]
    if not intervals:
        return RequirementMatch(requirement, "UNKNOWN", None)

    actual_years = total_experience_years(intervals, dt.date.today())
    if actual_years >= required_years:
        return RequirementMatch(requirement, "MET", f"{actual_years:.1f} years of work history on file")
    if actual_years >= required_years * 0.75:
        return RequirementMatch(
            requirement,
            "PARTIALLY_MET",
            f"{actual_years:.1f} years on file, close to the {required_years:.0f} asked for",
        )
    return RequirementMatch(requirement, "NOT_MET", f"Only {actual_years:.1f} years of work history on file")


_MATCHERS = {
    "skill": _match_skill,
    "education": _match_education,
    "certification": _match_certification,
    "domain_experience": _match_domain_experience,
    "years_experience": _match_years_experience,
}


def match_requirement(requirement: JobRequirement, profile: CandidateProfile) -> RequirementMatch:
    matcher = _MATCHERS.get(requirement.requirement_type, _match_skill)
    return matcher(requirement, profile)


def match_all(requirements: list[JobRequirement], profile: CandidateProfile | None) -> list[RequirementMatch]:
    if profile is None:
        return [RequirementMatch(r, "UNKNOWN", "No candidate profile on file yet") for r in requirements]
    return [match_requirement(r, profile) for r in requirements]
