"""
Stage 2 of the qualification pipeline (spec §21): one cheap structured-
output LLM call per job, extracting normalized requirements from its
description. Only ever runs after Stage 1's free checks.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.jobs import Job, JobRequirement
from app.services.llm.exceptions import LLMError
from app.services.llm.router import ModelRouter
from app.services.llm.schemas import JobRequirementsExtraction


async def extract_requirements(db: Session, job: Job) -> JobRequirementsExtraction | None:
    """
    Returns None (never raises) when no LLM is configured or extraction
    fails -- callers must treat that as "no structured requirements
    available," not a job failure, per spec §76: "the system must remain
    functional if the primary model becomes unavailable."
    """
    if not job.description:
        return None

    router = ModelRouter(db)
    messages = [
        {
            "role": "system",
            "content": (
                "You extract structured hiring requirements from a job posting's "
                "description. Return ONLY JSON matching the provided schema. For every "
                "requirement, mark whether it is required or preferred, give a confidence "
                "between 0 and 1, and quote the exact source text it came from. Never "
                "invent a requirement that isn't actually stated or clearly implied."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Job title: {job.title}\nCompany: {job.company}\n\n"
                f"Description:\n---\n{job.description}\n---"
            ),
        },
    ]
    try:
        return await router.get_structured(
            purpose="job_requirement_extraction",
            prompt_version="v1",
            messages=messages,
            response_model=JobRequirementsExtraction,
        )
    except LLMError:
        return None


def store_requirements(db: Session, job: Job, extraction: JobRequirementsExtraction) -> list[JobRequirement]:
    """
    Replaces any previously stored requirements for this job -- a
    re-qualification run should reflect the job's current description, not
    accumulate duplicates from earlier runs.
    """
    db.query(JobRequirement).filter(JobRequirement.job_id == job.id).delete()

    rows: list[JobRequirement] = []
    for req in extraction.requirements:
        row = JobRequirement(
            job_id=job.id,
            requirement_type=req.requirement_type,
            normalized_requirement=req.text,
            is_required=req.is_required,
            source_text=req.source_text,
            confidence=req.confidence,
            weight=1.0 if req.is_required else 0.5,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows
