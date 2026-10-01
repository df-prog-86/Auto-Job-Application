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

from sqlalchemy.orm import Session

from app.models.jobs import Job, JobEvaluation
from app.repositories.profile_repository import get_current_profile
from app.services.llm.exceptions import LLMError
from app.services.llm.router import ModelRouter
from app.services.llm.schemas import ResumeJobMatchResult
from app.services.qualification.resume_summary import summarize_candidate


class QualificationError(RuntimeError):
    """Scoring couldn't be completed (e.g. no LLM provider configured)."""


async def qualify_job(db: Session, job: Job) -> JobEvaluation:
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
                "for that the resume doesn't show, not vague statements. Be brief: the summary "
                "is at most two sentences, and list at most 8 gaps of under 15 words each. "
                "No text outside the JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                "Candidate background:\n---\n"
                f"{resume_text or '(no resume or profile on file yet)'}\n---\n\n"
                f"Job: {job.title} at {job.company}\n\n"
                "Job description:\n---\n"
                f"{job.description or '(no description available)'}\n---"
            ),
        },
    ]

    try:
        result = await router.get_structured(
            purpose="resume_job_match",
            prompt_version="v1",
            messages=messages,
            response_model=ResumeJobMatchResult,
        )
    except LLMError as exc:
        raise QualificationError(
            f"Couldn't score this job ({exc}). If this keeps happening, check the AI provider settings."
        ) from exc

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
