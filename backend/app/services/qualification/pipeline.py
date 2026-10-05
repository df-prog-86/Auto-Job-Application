"""
Qualification (Milestone 4, simplified): one direct LLM comparison of the
candidate's resume/profile against a job's description. See package
docstring (__init__.py) for why this replaced the earlier four-stage
pipeline.

Runs only when the candidate explicitly clicks "Score match" / "Re-score
match" on the Jobs page (app/api/jobs.py's POST /{job_id}/qualify) --
never automatically on add.
"""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app.models.jobs import Job, JobEvaluation
from app.repositories.profile_repository import get_current_profile
from app.services.llm.exceptions import LLMError
from app.services.llm.router import ModelRouter
from app.services.llm.schemas import ResumeJobMatchResult
from app.services.qualification.resume_summary import summarize_candidate


class QualificationError(RuntimeError):
    """Scoring couldn't be completed (e.g. no LLM provider configured)."""


def _salvage_match(raw: str) -> ResumeJobMatchResult | None:
    """
    Some models occasionally run on in the summary until they are cut off, which
    leaves broken JSON. The score itself is normally already written by then, so
    keep it and a short, clean version of whatever summary text there was.
    """
    score = re.search(r'"match_percentage"\s*:\s*(\d{1,3})', raw)
    if not score or int(score.group(1)) > 100:
        return None
    summary = ""
    text = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)', raw)
    if text:
        try:
            summary = json.loads(f'"{text.group(1)}"')
        except ValueError:
            summary = text.group(1)
        summary = " ".join(summary.split())[:400]
        cut = summary.rfind(".")
        summary = summary[: cut + 1] if cut > 40 else summary.rstrip(" ,;") + "..."
    return ResumeJobMatchResult(
        match_percentage=int(score.group(1)),
        summary=summary or "Scored from your resume. The detailed explanation was too long to keep, so re-score for a full summary.",
        gaps=[],
    )


async def score_against(db: Session, *, title: str, company: str, description: str | None) -> ResumeJobMatchResult:
    """One resume-vs-posting comparison. Nothing is saved; callers decide what to keep."""
    profile = get_current_profile(db)
    resume_text = summarize_candidate(profile)

    router = ModelRouter(db)
    messages = [
        {
            "role": "system",
            "content": (
                "You compare a candidate's resume/background against a job posting "
                "and judge how well they fit. Return ONLY JSON matching the provided "
                "schema. Base the score only on what's actually stated in the resume "
                "material and the job description -- never assume unstated skills or "
                "experience. List gaps as specific, concrete things the posting asks "
                "for that the resume doesn't show, not vague statements. HARD LENGTH LIMITS: "
                "the summary must be at most 300 characters (two short sentences); list at most 8 "
                "gaps, each at most 80 characters; the whole reply must stay under 1,200 characters. "
                "Stop as soon as the JSON is complete. No text outside the JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                "Candidate background:\n---\n"
                f"{resume_text or '(no resume or profile on file yet)'}\n---\n\n"
                f"Job: {title} at {company}\n\n"
                "Job description:\n---\n"
                f"{description or '(no description available)'}\n---"
            ),
        },
    ]

    try:
        result = await router.get_structured(
            purpose="resume_job_match",
            prompt_version="v1",
            messages=messages,
            response_model=ResumeJobMatchResult,
            # A score and a short explanation never need more than this; capping it
            # makes a runaway reply fail fast and cheaply instead of filling 4000 tokens.
            max_tokens=900,
            temperature=0.2,
            salvage=_salvage_match,
        )
    except LLMError as exc:
        raise QualificationError(
            f"Couldn't score this job ({exc}). If this keeps happening, check the AI provider settings."
        ) from exc
    return result


async def qualify_job(db: Session, job: Job) -> JobEvaluation:
    result = await score_against(db, title=job.title, company=job.company, description=job.description)

    evaluation = db.query(JobEvaluation).filter(JobEvaluation.job_id == job.id).first()
    if evaluation is None:
        evaluation = JobEvaluation(job_id=job.id)
        db.add(evaluation)

    evaluation.overall_score = round(result.match_percentage / 100, 3)
    evaluation.summary = result.summary
    evaluation.gaps = result.gaps
    evaluation.model_used = "resume_job_match_v1"
    evaluation.evaluation_version = "2"

    db.commit()
    db.refresh(evaluation)
    return evaluation
