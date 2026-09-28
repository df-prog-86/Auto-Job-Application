"""
Stage 4 of the qualification pipeline (spec §23): combines Stages 1-3 into
an interpretable weighted score. Every component is stored separately on
JobEvaluation so the UI can show *why* a job scored the way it did, per
spec's explicit requirement -- never just one opaque percentage.
"""

from __future__ import annotations

from app.services.qualification.evidence_matching import RequirementMatch
from app.services.qualification.hard_constraints import HardConstraintResult

_STATUS_WEIGHT = {"MET": 1.0, "PARTIALLY_MET": 0.5, "NOT_MET": 0.0, "UNKNOWN": 0.5}

# spec §23's recommended initial framework -- product-configurable later,
# not a universal truth.
WEIGHTS = {
    "required_coverage": 0.55,
    "preferred_score": 0.15,
    "domain_alignment": 0.10,
    "seniority_alignment": 0.10,
    "preference_alignment": 0.10,
}

_PREFERENCE_KEYS = ("workplace_type", "location", "salary", "employment_type")


def _coverage(matches: list[RequirementMatch]) -> float:
    if not matches:
        return 1.0  # nothing stated to fall short of
    return sum(_STATUS_WEIGHT[m.status] for m in matches) / len(matches)


def score_job(hard_result: HardConstraintResult, matches: list[RequirementMatch]) -> dict:
    required_matches = [m for m in matches if m.requirement.is_required]
    preferred_matches = [m for m in matches if not m.requirement.is_required]
    domain_matches = [m for m in matches if m.requirement.requirement_type == "domain_experience"]

    required_coverage = _coverage(required_matches)
    preferred_score = _coverage(preferred_matches)
    domain_alignment = _coverage(domain_matches) if domain_matches else 1.0

    seniority_status = hard_result.constraints.get("seniority", "UNKNOWN")
    seniority_alignment = {"PASS": 1.0, "FAIL": 0.0, "UNKNOWN": 0.7}[seniority_status]

    preference_statuses = [hard_result.constraints.get(k, "UNKNOWN") for k in _PREFERENCE_KEYS]
    preference_alignment = sum(
        1.0 if s == "PASS" else (0.5 if s == "UNKNOWN" else 0.0) for s in preference_statuses
    ) / len(preference_statuses)

    overall_score = (
        WEIGHTS["required_coverage"] * required_coverage
        + WEIGHTS["preferred_score"] * preferred_score
        + WEIGHTS["domain_alignment"] * domain_alignment
        + WEIGHTS["seniority_alignment"] * seniority_alignment
        + WEIGHTS["preference_alignment"] * preference_alignment
    )

    # Structured, not a flattened string -- lets the UI group gaps by
    # category (skills, experience, education, ...) instead of dumping one
    # long comma-separated line.
    gaps = [
        {"requirement": m.requirement.normalized_requirement, "type": m.requirement.requirement_type}
        for m in required_matches
        if m.status == "NOT_MET"
    ]

    return {
        "hard_filter_result": hard_result.overall,
        "required_coverage": round(required_coverage, 3),
        "preferred_score": round(preferred_score, 3),
        "domain_alignment": round(domain_alignment, 3),
        "seniority_alignment": round(seniority_alignment, 3),
        "preference_alignment": round(preference_alignment, 3),
        "overall_score": round(overall_score, 3),
        "disqualifiers": hard_result.disqualifiers,
        "gaps": gaps,
    }
