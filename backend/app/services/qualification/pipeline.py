"""
Orchestrates all four qualification stages for one job and stores the
result on JobEvaluation (spec §21-23). Runs automatically once a job is
added -- scoring is informational and free to redo. Nothing this produces
triggers tailoring or an application on its own; that only happens once the
candidate clicks "Proceed with Application" on the Jobs page (see
Job.application_status and api/jobs.py).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.candidate import CandidateAnswer
from app.models.jobs import Job, JobEvaluation
from app.models.search import SearchProfile
from app.repositories.profile_repository import get_current_profile
from app.services.qualification import evidence_matching
from app.services.qualification.hard_constraints import evaluate_hard_constraints
from app.services.qualification.requirement_extraction import extract_requirements, store_requirements
from app.services.qualification.scoring import score_job


async def qualify_job(db: Session, job: Job) -> JobEvaluation:
    search_profiles = db.query(SearchProfile).filter(SearchProfile.enabled.is_(True)).all()
    candidate_answers = db.query(CandidateAnswer).all()
    profile = get_current_profile(db)

    hard_result = evaluate_hard_constraints(job, search_profiles, candidate_answers)

    extraction = await extract_requirements(db, job)
    requirements = store_requirements(db, job, extraction) if extraction is not None else []

    matches = evidence_matching.match_all(requirements, profile)
    scored = score_job(hard_result, matches)

    evaluation = db.query(JobEvaluation).filter(JobEvaluation.job_id == job.id).first()
    if evaluation is None:
        evaluation = JobEvaluation(job_id=job.id)
        db.add(evaluation)

    evaluation.hard_filter_result = scored["hard_filter_result"]
    evaluation.required_coverage = scored["required_coverage"]
    evaluation.preferred_score = scored["preferred_score"]
    evaluation.domain_alignment = scored["domain_alignment"]
    evaluation.seniority_alignment = scored["seniority_alignment"]
    evaluation.preference_alignment = scored["preference_alignment"]
    evaluation.overall_score = scored["overall_score"]
    evaluation.disqualifiers = scored["disqualifiers"]
    evaluation.gaps = scored["gaps"]
    # ModelRouter doesn't currently surface which specific model succeeded
    # (FAST vs FALLBACK) back to the caller -- rather than guess, this is
    # left honest: set only when we know extraction actually ran.
    evaluation.model_used = "job_requirement_extraction_v1" if extraction is not None else None
    evaluation.evaluation_version = "1"

    db.commit()
    db.refresh(evaluation)
    return evaluation
