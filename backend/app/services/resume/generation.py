"""
Asks the model to select and reword the candidate's own approved claims for
one job, then validates the result (see validation.py). One retry with the
problems fed back; if it still fails, falls back to the candidate's original
wording rather than ever shipping unvalidated text (spec §26).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.candidate import CandidateProfile
from app.models.jobs import Job
from app.services.llm.exceptions import LLMError
from app.services.llm.router import ModelRouter
from app.services.llm.schemas import TailoredResumeContent
from app.services.resume.validation import (
    ClaimRef,
    EmploymentRef,
    original_wording_content,
    validate_content,
)


@dataclass
class GenerationResult:
    content: TailoredResumeContent
    used_original_wording: bool
    problems: list[str] = field(default_factory=list)


def refs_from_profile(profile: CandidateProfile) -> tuple[list[ClaimRef], list[EmploymentRef], list[str]]:
    claims = [
        ClaimRef(id=c.id, text=c.canonical_text, employer=c.employer, skills=tuple(c.skills or []))
        for c in profile.verified_claims
        if c.verified
    ]
    employment = [EmploymentRef(id=e.id, employer=e.employer, title=e.title) for e in profile.employment_history]
    skills = [s.canonical_skill for s in profile.skills]
    return claims, employment, skills


def _build_messages(job: Job, claims, employment, skills) -> list[dict[str, str]]:
    claim_lines = "\n".join(f"[{c.id}] ({c.employer or 'no employer'}) {c.text}" for c in claims)
    job_lines = "\n".join(f"employment_id={e.id}: {e.title} at {e.employer}" for e in employment)
    return [
        {
            "role": "system",
            "content": (
                "You tailor a resume for one job using ONLY the candidate's verified claims. "
                "Return ONLY JSON matching the schema. Rules: choose the claims most relevant to "
                "the job and put the strongest first; you may rephrase a claim but must not add "
                "facts, numbers, tools, or responsibilities it doesn't state; every bullet and the "
                "summary must list the claim ids it is based on; bullets go under the employment "
                "the claim belongs to; skills may only come from the candidate's skill list; drop "
                "irrelevant content. Do not include dates, employer names, or titles in bullet text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Job: {job.title} at {job.company}\n\nJob description:\n---\n"
                f"{job.description or '(none)'}\n---\n\n"
                f"Employment entries:\n{job_lines}\n\nVerified claims:\n{claim_lines}\n\n"
                f"Candidate skills: {', '.join(skills)}"
            ),
        },
    ]


async def generate_tailored_content(db: Session, job: Job, profile: CandidateProfile) -> GenerationResult:
    claims, employment, skills = refs_from_profile(profile)
    fallback = original_wording_content(claims=claims, employment=employment, candidate_skills=skills)
    if not claims:
        return GenerationResult(fallback, True, ["no approved claims on file"])

    router = ModelRouter(db)
    messages = _build_messages(job, claims, employment, skills)
    all_problems: list[str] = []

    for attempt in range(2):
        try:
            content = await router.get_structured(
                purpose="resume_tailoring",
                prompt_version="v1",
                messages=messages,
                response_model=TailoredResumeContent,
            )
        except LLMError as exc:
            all_problems.append(f"model call failed: {exc}")
            break

        problems = validate_content(content, claims=claims, employment=employment, candidate_skills=skills)
        if not problems:
            return GenerationResult(content, False, [])

        all_problems.extend(problems)
        messages = messages + [
            {
                "role": "user",
                "content": "That output failed validation: " + "; ".join(problems) + ". Fix these and return corrected JSON.",
            }
        ]

    return GenerationResult(fallback, True, all_problems)
