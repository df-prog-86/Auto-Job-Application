"""Milestone 5: the checks that stop tailored resumes from inventing facts."""

from app.services.llm.schemas import TailoredBullet, TailoredExperience, TailoredResumeContent
from app.services.resume.validation import (
    ClaimRef,
    EmploymentRef,
    original_wording_content,
    validate_content,
)

CLAIMS = [
    ClaimRef(1, "Reduced report time by 40% using SQL", "Acme", ("SQL",)),
    ClaimRef(2, "Led a team of 5 analysts", "Acme"),
    ClaimRef(3, "Built dashboards in Tableau", "Beta", ("Tableau",)),
]
EMPLOYMENT = [EmploymentRef(10, "Acme", "Analyst"), EmploymentRef(11, "Beta", "Intern")]
SKILLS = ["SQL", "Tableau"]


def _problems(content: TailoredResumeContent) -> list[str]:
    return validate_content(content, claims=CLAIMS, employment=EMPLOYMENT, candidate_skills=SKILLS)


def _one_bullet(text: str, ids: list[int], employment_id: int = 10) -> TailoredResumeContent:
    return TailoredResumeContent(
        experience=[
            TailoredExperience(employment_id=employment_id, bullets=[TailoredBullet(text=text, source_claim_ids=ids)])
        ]
    )


def test_valid_content_passes():
    content = TailoredResumeContent(
        summary="SQL analyst who led a team of 5",
        summary_source_claim_ids=[2],
        experience=_one_bullet("Cut report time 40% with SQL", [1]).experience,
        skills=["SQL"],
    )
    assert _problems(content) == []


def test_invented_number_rejected():
    assert _problems(_one_bullet("Cut report time 60%", [1]))


def test_unknown_claim_rejected():
    assert _problems(_one_bullet("anything", [99]))


def test_bullet_without_claims_rejected():
    assert _problems(_one_bullet("anything", []))


def test_claim_from_other_employer_rejected():
    assert _problems(_one_bullet("Built dashboards in Tableau", [3]))


def test_unknown_employment_rejected():
    assert _problems(_one_bullet("anything", [1], employment_id=77))


def test_invented_skill_rejected():
    assert _problems(TailoredResumeContent(skills=["Kubernetes"]))


def test_summary_needs_claims():
    assert _problems(TailoredResumeContent(summary="Great person"))


def test_original_wording_fallback_is_valid():
    assert _problems(original_wording_content(claims=CLAIMS, employment=EMPLOYMENT, candidate_skills=SKILLS)) == []
