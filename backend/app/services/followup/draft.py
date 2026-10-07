"""
A short follow-up note the candidate can edit and send themselves. The app
never sends anything. The draft may use only facts we hold (the job title,
the company, the candidate's name, roughly how long ago they applied): it
must not invent a contact person, a date, or an achievement.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.jobs import Job
from app.repositories.profile_repository import get_current_profile
from app.services.llm.exceptions import LLMError
from app.services.llm.router import ModelRouter

Kind = Literal["after_applying", "after_interview"]


class FollowUpDraftError(RuntimeError):
    """The draft couldn't be written (e.g. no AI connection set up)."""


class FollowUpDraft(BaseModel):
    subject: str = Field(description="Email subject line, at most 70 characters")
    body: str = Field(description="The message, at most 80 words, plain text, no placeholders")


def _days_ago(job: Job) -> int | None:
    if job.applied_at is None:
        return None
    applied = job.applied_at if job.applied_at.tzinfo else job.applied_at.replace(tzinfo=dt.timezone.utc)
    return max(0, (dt.datetime.now(dt.timezone.utc) - applied).days)


def _clean(text: str) -> str:
    # The app never uses em or en dashes in anything the person sees.
    return text.replace("—", ",").replace("–", "-").strip()


async def draft_follow_up(db: Session, job: Job, kind: Kind = "after_applying") -> FollowUpDraft:
    profile = get_current_profile(db)
    first_name = (profile.preferred_name or profile.name or "").split()[0] if profile and (profile.preferred_name or profile.name) else ""
    days = _days_ago(job)
    when = f"about {days} days ago" if days is not None and days > 1 else "recently"
    if kind == "after_interview":
        ask = f"Write a brief thank-you note after interviewing for the {job.title} role at {job.company}. Restate interest in the role."
    else:
        ask = (
            f"Write a brief, polite follow-up about the candidate's application for the {job.title} role at "
            f"{job.company}, submitted {when}. Restate interest and ask whether there is any update."
        )
    messages = [
        {
            "role": "system",
            "content": (
                "You write short, warm, professional emails for a job seeker. Return ONLY JSON matching the schema. "
                "Rules: at most 80 words; three or four short sentences; plain text; no placeholders or brackets; "
                "start with 'Hello,' (never invent a recipient's name); do not invent facts, dates, projects or "
                "achievements; do not exaggerate; do not use dashes as punctuation; end with a thanks and the "
                f"first name '{first_name or 'the candidate'}' on its own line."
            ),
        },
        {"role": "user", "content": ask},
    ]
    try:
        result = await ModelRouter(db).get_structured(
            purpose="follow_up_draft",
            prompt_version="v1",
            messages=messages,
            response_model=FollowUpDraft,
            max_tokens=400,
            temperature=0.5,
        )
    except LLMError as exc:
        raise FollowUpDraftError(f"Couldn't write the draft ({exc}). Check the AI provider settings.") from exc
    return FollowUpDraft(subject=_clean(result.subject)[:100], body=_clean(result.body))
