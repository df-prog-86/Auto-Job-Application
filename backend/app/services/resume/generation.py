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
    changelog: list[str] = field(default_factory=list)


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
                "You tailor a resume for one job using ONLY the candidate's verified claims, "
                "which come from their single master resume. Return ONLY JSON matching the schema.\n"
                "Edit philosophy (soft rephrase): keep wording as close to the claim as possible. "
                "Reorder ALL bullets within each employment by fit to the job description, best fit "
                "first, and include every claim for that employment. You may make tiny truthful word "
                "swaps and add a light lead-in that matches the job's language, woven into the "
                "substance of the bullet. Do not rewrite the candidate's voice and do not bolt "
                "keywords onto the front of bullets.\n"
                "Hard bans: never invent or imply tools, certifications, titles, employers, metrics, "
                "tenure, or specialties the claims do not state. Never inflate years. If the job asks "
                "for something the claims do not support, leave it out of the resume and instead add a "
                "note about it to the changelog. Do not add a substitute line for a missing "
                "requirement.\n"
                "Every bullet and the summary must list the claim ids it is based on; put bullets "
                "under the employment the claim belongs to; skills may only come from the candidate's "
                "skill list. Do not put dates, employer names, or titles in bullet text. Never use em "
                "dashes or en dashes; use a comma, period, colon, or hyphen.\n"
                "changelog: short plain notes for the candidate covering what you reordered or "
                "lightly changed, and every gap (missing tools or certifications, years under the "
                "job's bar, anything required that the claims do not support)."
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
        return GenerationResult(
            fallback, True, ["no approved claims on file"], ["No approved claims on file, so nothing could be tailored."]
        )

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
            return GenerationResult(content, False, [], list(content.changelog))

        all_problems.extend(problems)
        messages = messages + [
            {
                "role": "user",
                "content": "That output failed validation: " + "; ".join(problems) + ". Fix these and return corrected JSON.",
            }
        ]

    notes = [
        "The AI's tailored version did not pass the accuracy checks, so this resume uses your original "
        "wording. Job-specific gaps were not analyzed for this version."
    ]
    return GenerationResult(fallback, True, all_problems, notes)
