"""
ORM models. Import every model module here so Alembic's autogenerate (and
`Base.metadata.create_all` in tests) sees the full schema.
"""

from app.models.accounts import CandidateAccount
from app.models.applications import Application, ApplicationAnswer, ApplicationEvent
from app.models.candidate import (
    CandidateAnswer,
    CandidateProfile,
    Certification,
    Education,
    EmploymentHistory,
    Skill,
    VerifiedClaim,
    VoluntaryDisclosure,
)
from app.models.discovery import TargetEmployer
from app.models.documents import GeneratedDocument
from app.models.job_search import JobSearchResult
from app.models.jobs import Job, JobEvaluation, JobSource
from app.models.mappings import FieldMapping, QuestionMapping
from app.models.model_runs import ModelRun
from app.models.questions import PendingQuestion
from app.models.search import SearchProfile
from app.models.system import AutomationState, ExtensionPairing

__all__ = [
    "JobSearchResult",
    "CandidateAccount",
    "Application",
    "ApplicationAnswer",
    "ApplicationEvent",
    "CandidateAnswer",
    "CandidateProfile",
    "Certification",
    "Education",
    "EmploymentHistory",
    "Skill",
    "VerifiedClaim",
    "VoluntaryDisclosure",
    "TargetEmployer",
    "GeneratedDocument",
    "Job",
    "JobEvaluation",
    "JobSource",
    "FieldMapping",
    "QuestionMapping",
    "ModelRun",
    "PendingQuestion",
    "SearchProfile",
    "ExtensionPairing",
    "AutomationState",
]
