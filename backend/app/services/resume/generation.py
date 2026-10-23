"""
Asks the model how to reorder and lightly reword the bullets of the master
resume for one job, then validates the plan (validation.py). One retry with
the problems fed back; if it still fails, the master's own order and wording
are kept (nothing unvalidated is ever applied).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.jobs import Job
from app.services.llm.exceptions import LLMError
from app.services.llm.router import ModelRouter
from app.services.llm.schemas import TailorPlan
from app.services.resume.docx_editor import Block, TextPart
from app.services.resume.validation import added_skills, sanitize_plan, validate_plan

logger = logging.getLogger("resume_tailor")


@dataclass
class PlanResult:
    plan: TailorPlan | None  # None = keep the master exactly as is
    problems: list[str] = field(default_factory=list)
    changelog: list[str] = field(default_factory=list)


SYSTEM_PROMPT = (
    "You tailor a resume for one job. The resume is the candidate's single master resume, "
    "given to you as blocks of bullets (each block is one role's bullet list). Return ONLY JSON "
    "matching the schema.\n"
    "Edit philosophy (light touch): keep the candidate's wording and voice. For every block, return "
    "ALL of its bullets exactly once, reordered by fit to the job description, best fit first. Where "
    "it clearly helps, you may make a few small, conservative word tweaks: swap a word or short phrase "
    "for the job description's own term when it means the same thing and the bullet already supports "
    "it (for example 'client' to 'patient' only if the bullet is truly about patients), or tighten "
    "a phrase. Change at most a few words in a bullet, and leave most bullets exactly as given. If a "
    "bullet needs no change, return its text exactly as given. Do not restructure sentences, do not "
    "rewrite the candidate's voice and do not bolt keywords onto the front of bullets.\n"
    "Summary paragraphs (listed as [S<id>]): return each one in 'summaries' with the same conservative rule: "
    "keep the paragraph as it is except for a few small, truthful word swaps toward the job's own terms. "
    "Keep its length about the same. Skills lines (listed as [K<id>]): return each in 'skills' with every "
    "item exactly once, spelled exactly as given, reordered so the items the job asks for come first. "
    "Never drop, rename or merge an existing skill. ATS keywords: you may add up to 5 skills in total "
    "across the skills lines, only generic professional competencies (for example project management, "
    "change management, team development, stakeholder engagement) that the job posting names word for "
    "word and that the master resume's experience clearly supports; add each to the skills line where "
    "it fits best. Never add a tool, software, system, certification, degree, employer or number that "
    "the master does not already name. You may also weave the job posting's own keywords into bullets "
    "and the summary when they honestly describe what that bullet or paragraph already shows. "
    "Anything else the job wants that the master lacks goes in the changelog only.\n"
    "Hard bans: never invent or imply tools, certifications, titles, employers, metrics, tenure, "
    "or specialties the master does not state. Never inflate years. If the job asks for something "
    "the master does not support, leave it out and instead add a note to the changelog. Do not add "
    "a substitute line for a missing requirement. Never use em dashes or en dashes.\n"
    "changelog: short plain notes for the candidate covering what you reordered or lightly changed "
    "and every gap (missing tools or certifications, years under the job's bar, anything required "
    "that the master does not support)."
)


FIRM_PROMPT = (
    "You tailor a resume for one job. The resume is the candidate's single master resume, "
    "given to you as blocks of bullets (each block is one role's bullet list). Return ONLY JSON "
    "matching the schema.\n"
    "Edit philosophy (firm tailor): shape the resume so it speaks to this job. For every block, "
    "return ALL of its bullets exactly once, reordered by fit to the job description, best fit first. "
    "You may rewrite how a bullet is phrased: lead with the part most relevant to the job, restructure "
    "the sentence, and use the job description's own vocabulary where the bullet or the master resume "
    "truthfully supports it. Keep each bullet about the same length as the original (never more than "
    "about a quarter longer) so the page layout does not change. Do not merge or split bullets. A bullet "
    "that already fits the job may stay as it is.\n"
    "Summary paragraphs (listed as [S<id>]): return each one in 'summaries', rewritten so it speaks to this "
    "job: lead with what matters most to it and use the job's vocabulary where the paragraph truthfully supports "
    "it, using only facts already in the paragraph or the bullets. Keep it about the same length. Skills lines "
    "(listed as [K<id>]): return each in 'skills' with every item exactly once, spelled exactly as given, "
    "reordered so the items the job asks for come first. "
    "Never drop, rename or merge an existing skill. ATS keywords: you may add up to 5 skills in total "
    "across the skills lines, only generic professional competencies (for example project management, "
    "change management, team development, stakeholder engagement) that the job posting names word for "
    "word and that the master resume's experience clearly supports; add each to the skills line where "
    "it fits best. Never add a tool, software, system, certification, degree, employer or number that "
    "the master does not already name. You may also weave the job posting's own keywords into bullets "
    "and the summary when they honestly describe what that bullet or paragraph already shows. "
    "Anything else the job wants that the master lacks goes in the changelog only.\n"
    "In the summary you may use ordinary descriptive words (skilled, experienced, proficient and the like) "
    "where the master supports the claim, but never name a tool, system, technology or credential that is "
    "not in the master.\n"
    "Hard bans: every fact must come from the master: the same employers, titles, tools, numbers, "
    "scope and tenure. Never invent or imply tools, certifications, titles, employers, metrics, or "
    "specialties the master does not state. Never add numbers. Never inflate years or responsibility. "
    "If the job asks for something the master does not support, leave it out and instead add a note to "
    "the changelog. Do not add a substitute line for a missing requirement. Never use em dashes or en dashes.\n"
    "changelog: short plain notes for the candidate covering what you reordered, what you rephrased "
    "and every gap (missing tools or certifications, years under the job's bar, anything required "
    "that the master does not support)."
)


def plan_changes(plan: TailorPlan, blocks: list[Block], parts: list[TextPart]) -> dict[str, int | bool]:
    """What a plan really does to the master, counted from the plan itself (never from what the AI says it did)."""
    by_id = {p.id: p for p in parts}
    originals = {b.id: b for block in blocks for b in block.bullets}
    block_ids = {block.id: [b.id for b in block.bullets] for block in blocks}
    reordered_roles = sum(1 for pb in plan.blocks if pb.block_id in block_ids and [b.bullet_id for b in pb.bullets] != block_ids[pb.block_id])
    reworded = sum(1 for pb in plan.blocks for b in pb.bullets if b.bullet_id in originals and b.text != originals[b.bullet_id].text)
    summary = any(p.text != by_id[p.part_id].text for p in plan.summaries if p.part_id in by_id)
    skills_reordered = any(
        [i.strip() for i in p.items][: len(by_id[p.part_id].items)] != by_id[p.part_id].items for p in plan.skills if p.part_id in by_id
    )
    added = len(added_skills(plan, parts))
    return {
        "reordered_roles": reordered_roles, "reworded": reworded, "summary": summary,
        "skills_reordered": skills_reordered, "skills_added": added,
    }


def is_no_change(changes: dict[str, int | bool]) -> bool:
    return not any(changes.values())


# A note the AI wrote about something the master lacks is kept; a note about what it supposedly changed is not, since the code states that itself.
_CLAIMED_CHANGE = re.compile(r"\b(reorder\w*|rephras\w*|reword\w*|rewrote|rewritten|emphasi[sz]\w*|prioriti[sz]\w*|added|adjust\w*|align\w*|moved|tailor\w*)\b", re.I)


def _gap_notes(changelog: list[str]) -> list[str]:
    return [n.strip() for n in changelog if n.strip() and not _CLAIMED_CHANGE.search(n)]


def _change_notes(plan: TailorPlan, blocks: list[Block], parts: list[TextPart], existing: list[str] | None = None) -> list[str]:
    """Plain notes written by the code itself from what the plan really changes, so "What changed" is always true."""
    c = plan_changes(plan, blocks, parts)
    notes: list[str] = []
    if c["summary"]:
        notes.append("Reworded your summary for this job. Read it over to make sure it still sounds like you.")
    if c["skills_reordered"]:
        notes.append("Reordered your skills so the ones this job asks for come first.")
    if c["reordered_roles"]:
        n = c["reordered_roles"]
        notes.append(f"Reordered the bullets in {n} {'role' if n == 1 else 'roles'} so the ones closest to this job come first.")
    if c["reworded"]:
        n = c["reworded"]
        notes.append(f"Reworded {n} {'bullet' if n == 1 else 'bullets'} to fit the job.")
    return notes


def _final_notes(plan: TailorPlan, blocks: list[Block], parts: list[TextPart]) -> list[str]:
    """The changelog shown to the person: what really changed (counted by the code), then the AI's notes on what the master lacks."""
    notes = _change_notes(plan, blocks, parts) + _added_note(plan, parts)
    if not notes:
        notes.append("Nothing was changed: the resume already leads with what this job asks for, or the edits were not safe to make.")
    return notes + _gap_notes(list(plan.changelog))


def _added_note(plan: TailorPlan, parts: list[TextPart]) -> list[str]:
    extra = added_skills(plan, parts)
    if not extra:
        return []
    return ["Added to your skills from the job posting (check each one fits you): " + ", ".join(extra) + "."]


def _parts_text(parts: list[TextPart]) -> str:
    lines: list[str] = []
    for p in parts:
        if p.kind == "summary":
            lines.append(f"  [S{p.id}] {p.text}")
        else:
            lines.append(f"  [K{p.id}] {p.label}{' | '.join(p.items)}")
    return "\n".join(lines)


def _blocks_text(blocks: list[Block]) -> str:
    lines: list[str] = []
    for block in blocks:
        lines.append(f"Block {block.id} (context: {block.context or 'none'})")
        lines.extend(f"  [{b.id}] {b.text}" for b in block.bullets)
    return "\n".join(lines)


async def generate_plan(
    db: Session, job: Job, blocks: list[Block], master_text: str, strength: str = "light",
    parts: list[TextPart] | None = None,
) -> PlanResult:
    firm = strength == "firm"
    parts = parts or []
    if not blocks and not parts:
        return PlanResult(None, [], ["No bulleted experience was found in the master resume, so nothing was reordered."])

    router = ModelRouter(db)
    messages = [
        {"role": "system", "content": FIRM_PROMPT if firm else SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Job: {job.title} at {job.company}\n\nJob description:\n---\n"
                f"{job.description or '(none)'}\n---\n\nMaster resume bullets:\n{_blocks_text(blocks)}"
                + (f"\n\nSummary and skills (part ids are the numbers after S and K):\n{_parts_text(parts)}" if parts else "")
            ),
        },
    ]
    all_problems: list[str] = []
    last_plan: TailorPlan | None = None
    for attempt in range(3):
        try:
            plan = await router.get_structured(
                purpose="resume_tailoring",
                prompt_version="v4-firm-sections" if firm else "v3-light-sections",
                messages=messages,
                response_model=TailorPlan,
            )
        except LLMError as exc:
            all_problems.append(f"model call failed: {exc}")
            break
        last_plan = plan
        problems = validate_plan(plan, blocks, master_text, firm, parts, job.description or "")
        if not problems:
            if is_no_change(plan_changes(plan, blocks, parts)) and attempt == 0:
                # A plan that changes nothing, while the notes may claim otherwise: ask once for a real tailoring.
                logger.warning("resume tailor (%s) returned a plan with no changes; asking again", strength)
                messages = messages + [
                    {
                        "role": "user",
                        "content": (
                            "That plan is identical to the master resume: no bullet was moved or reworded and the summary and skills are unchanged. "
                            + (
                                "A firm tailor must visibly change it: reorder every role's bullets by fit to the job, rephrase the bullets that "
                                "matter most for this job (and the summary) in the job's own vocabulary using only facts already in the master, "
                                "and reorder the skills. "
                                if firm
                                else "Reorder every role's bullets by fit to the job, best first, put the skills the job asks for first, and make the "
                                "few small word swaps toward the job's own terms that the master truthfully supports. "
                            )
                            + "Only keep something unchanged if it is already the best fit. Return corrected JSON."
                        ),
                    }
                ]
                continue
            return PlanResult(plan, [], _final_notes(plan, blocks, parts))
        logger.warning("resume tailor (%s) failed checks: %s", strength, "; ".join(problems)[:1500])
        all_problems.extend(problems)
        messages = messages + [
            {
                "role": "user",
                "content": "That output failed validation: " + "; ".join(problems) + ". Return corrected JSON.",
            }
        ]

    if last_plan is not None:
        # Keep the parts that passed and put back the original for the rest, rather than losing everything.
        cleaned, notes = sanitize_plan(last_plan, blocks, master_text, firm, parts, job.description or "")
        if not validate_plan(cleaned, blocks, master_text, firm, parts, job.description or ""):
            skipped = sorted(set(notes))
            return PlanResult(
                cleaned,
                [],
                _final_notes(cleaned, blocks, parts)
                + (["Some edits didn't pass the accuracy checks and were left as you wrote them:"] + skipped if skipped else []),
            )

    return PlanResult(
        None,
        all_problems,
        [
            "The AI's tailoring did not pass the accuracy checks, so this resume is your master "
            "unchanged (apart from dash cleanup). Job-specific gaps were not analyzed."
        ],
    )
