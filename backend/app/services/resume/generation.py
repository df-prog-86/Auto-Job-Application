"""
Asks the model how to reorder and lightly reword the bullets of the master
resume for one job, then validates the plan (validation.py). One retry with
the problems fed back; if it still fails, the master's own order and wording
are kept (nothing unvalidated is ever applied).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.jobs import Job
from app.services.llm.exceptions import LLMError
from app.services.llm.router import ModelRouter
from app.services.llm.schemas import TailorPlan
from app.services.resume.docx_editor import Block
from app.services.resume.validation import validate_plan


@dataclass
class PlanResult:
    plan: TailorPlan | None  # None = keep the master exactly as is
    problems: list[str] = field(default_factory=list)
    changelog: list[str] = field(default_factory=list)


SYSTEM_PROMPT = (
    "You tailor a resume for one job. The resume is the candidate's single master resume, "
    "given to you as blocks of bullets (each block is one role's bullet list). Return ONLY JSON "
    "matching the schema.\n"
    "Edit philosophy (soft rephrase): keep wording as close to the original as possible. For every "
    "block, return ALL of its bullets exactly once, reordered by fit to the job description, best "
    "fit first. Only tiny truthful word swaps or a light lead-in that matches the job's language "
    "are allowed, woven into the substance of the bullet. If a bullet needs no change, return its "
    "text exactly as given. Do not rewrite the candidate's voice and do not bolt keywords onto the "
    "front of bullets.\n"
    "Hard bans: never invent or imply tools, certifications, titles, employers, metrics, tenure, "
    "or specialties the master does not state. Never inflate years. If the job asks for something "
    "the master does not support, leave it out and instead add a note to the changelog. Do not add "
    "a substitute line for a missing requirement. Never use em dashes or en dashes.\n"
    "changelog: short plain notes for the candidate covering what you reordered or lightly changed "
    "and every gap (missing tools or certifications, years under the job's bar, anything required "
    "that the master does not support)."
)


def _blocks_text(blocks: list[Block]) -> str:
    lines: list[str] = []
    for block in blocks:
        lines.append(f"Block {block.id} (context: {block.context or 'none'})")
        lines.extend(f"  [{b.id}] {b.text}" for b in block.bullets)
    return "\n".join(lines)


async def generate_plan(db: Session, job: Job, blocks: list[Block], master_text: str) -> PlanResult:
    if not blocks:
        return PlanResult(None, [], ["No bulleted experience was found in the master resume, so nothing was reordered."])

    router = ModelRouter(db)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Job: {job.title} at {job.company}\n\nJob description:\n---\n"
                f"{job.description or '(none)'}\n---\n\nMaster resume bullets:\n{_blocks_text(blocks)}"
            ),
        },
    ]
    all_problems: list[str] = []
    for _ in range(2):
        try:
            plan = await router.get_structured(
                purpose="resume_tailoring",
                prompt_version="v2",
                messages=messages,
                response_model=TailorPlan,
            )
        except LLMError as exc:
            all_problems.append(f"model call failed: {exc}")
            break
        problems = validate_plan(plan, blocks, master_text)
        if not problems:
            return PlanResult(plan, [], list(plan.changelog))
        all_problems.extend(problems)
        messages = messages + [
            {
                "role": "user",
                "content": "That output failed validation: " + "; ".join(problems) + ". Return corrected JSON.",
            }
        ]

    return PlanResult(
        None,
        all_problems,
        [
            "The AI's tailoring did not pass the accuracy checks, so this resume is your master "
            "unchanged (apart from dash cleanup). Job-specific gaps were not analyzed."
        ],
    )
