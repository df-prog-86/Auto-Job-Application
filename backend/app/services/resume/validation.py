"""
Deterministic checks on the model's tailoring plan. Pure logic, no database
or LLM access.

Enforced: every role's bullets come back exactly once (none dropped, added,
duplicated, or moved to another role); any reworded bullet keeps at least 60%
of its original words, adds no numbers, and adds no capitalized or numeric
term (a tool, certification, employer) that doesn't already appear somewhere
in the master resume.

Not catchable: a reword that implies something stronger using only words
already in the master. The wording limits make that small, and the UI tells
the candidate to read the result.
"""

from __future__ import annotations

import re

from app.services.llm.schemas import TailorPlan
from app.services.resume.docx_editor import Block, TextPart

MIN_WORDS_KEPT = 0.6  # light tailor
MIN_WORDS_KEPT_FIRM = 0.4  # firm tailor may rephrase more
MAX_LENGTH_GROWTH_LIGHT = 1.1  # a light summary tweak barely changes length
MAX_LENGTH_GROWTH_FIRM = 1.25  # a firm rewrite stays about as long, so the page layout does not shift
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_WORD = re.compile(r"[a-z0-9]+")
_TERM = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#./-]*")


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "") for m in _NUMBER.finditer(text)}


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def validate_plan(
    plan: TailorPlan, blocks: list[Block], master_text: str, firm: bool = False, parts: list[TextPart] | None = None
) -> list[str]:
    problems: list[str] = []
    blocks_by_id = {b.id: b for b in blocks}
    vocabulary = _words(master_text)
    seen_blocks: set[int] = set()

    for planned in plan.blocks:
        block = blocks_by_id.get(planned.block_id)
        if block is None:
            problems.append(f"unknown block id {planned.block_id}")
            continue
        if planned.block_id in seen_blocks:
            problems.append(f"block {planned.block_id} appears more than once")
        seen_blocks.add(planned.block_id)

        original = {b.id: b for b in block.bullets}
        ids = [b.bullet_id for b in planned.bullets]
        if sorted(ids) != sorted(original):
            problems.append(
                f"block {planned.block_id} must contain each of its bullets exactly once "
                f"(expected {sorted(original)}, got {sorted(ids)})"
            )
            continue

        for bullet in planned.bullets:
            problems.extend(_check_rewrite(bullet.bullet_id, original[bullet.bullet_id].text, bullet.text, vocabulary, firm))
    problems.extend(_validate_text_parts(plan, parts or [], vocabulary, firm))
    return problems


def _validate_text_parts(plan: TailorPlan, parts: list[TextPart], vocabulary: set[str], firm: bool) -> list[str]:
    problems: list[str] = []
    by_id = {p.id: p for p in parts}
    seen: set[int] = set()
    for planned in plan.summaries:
        part = by_id.get(planned.part_id)
        if part is None or part.kind != "summary":
            problems.append(f"unknown summary id {planned.part_id}")
            continue
        if planned.part_id in seen:
            problems.append(f"summary {planned.part_id} appears more than once")
        seen.add(planned.part_id)
        problems.extend(
            _check_rewrite(
                planned.part_id, part.text, planned.text, vocabulary, firm,
                label="summary", max_growth=MAX_LENGTH_GROWTH_FIRM if firm else MAX_LENGTH_GROWTH_LIGHT,
            )
        )
    for planned in plan.skills:
        part = by_id.get(planned.part_id)
        if part is None or part.kind != "skills":
            problems.append(f"unknown skills id {planned.part_id}")
            continue
        if planned.part_id in seen:
            problems.append(f"skills line {planned.part_id} appears more than once")
        seen.add(planned.part_id)
        if sorted(i.strip().lower() for i in planned.items) != sorted(i.lower() for i in part.items):
            problems.append(
                f"skills line {planned.part_id} must contain each of its items exactly once, spelled as given "
                f"(expected {part.items})"
            )
    return problems


def skills_to_dict(plan: TailorPlan, parts: list[TextPart]) -> dict[int, list[str]]:
    """Skills orders with each item restored to its exact original spelling."""
    by_id = {p.id: p for p in parts}
    out: dict[int, list[str]] = {}
    for planned in plan.skills:
        part = by_id.get(planned.part_id)
        if part is None:
            continue
        spelled = {i.lower(): i for i in part.items}
        out[planned.part_id] = [spelled[i.strip().lower()] for i in planned.items]
    return out


def summaries_to_dict(plan: TailorPlan) -> dict[int, str]:
    return {s.part_id: s.text for s in plan.summaries}


def _check_rewrite(
    bullet_id: int, original: str, new: str, vocabulary: set[str], firm: bool = False,
    label: str = "bullet", max_growth: float | None = None,
) -> list[str]:
    if new == original:
        return []
    problems: list[str] = []
    label = f"{label} {bullet_id}"

    introduced = _numbers(new) - _numbers(original)
    if introduced:
        problems.append(f"{label} introduces numbers not in the original: {sorted(introduced)}")

    original_words = _words(original)
    if original_words:
        kept = len(original_words & _words(new)) / len(original_words)
        if kept < (MIN_WORDS_KEPT_FIRM if firm else MIN_WORDS_KEPT):
            problems.append(f"{label} rewords the original too heavily (keeps {kept:.0%} of its words)")

    if max_growth is None and firm:
        max_growth = MAX_LENGTH_GROWTH_FIRM
    if max_growth is not None and len(new) > len(original) * max_growth + 10:
        problems.append(f"{label} is much longer than the original, which could change the page layout")

    for index, term in enumerate(_TERM.findall(new)):
        lowered = term.lower()
        if index == 0 or lowered in original_words or lowered in vocabulary:
            continue
        if term[0].isupper() or any(c.isdigit() for c in term):
            problems.append(f"{label} introduces a term not found in the master resume: {term!r}")
    return problems


def plan_to_dict(plan: TailorPlan) -> dict[int, list[tuple[int, str]]]:
    return {p.block_id: [(b.bullet_id, b.text) for b in p.bullets] for p in plan.blocks}


def sanitize_plan(
    plan: TailorPlan, blocks: list[Block], master_text: str, firm: bool = False, parts: list[TextPart] | None = None
) -> tuple[TailorPlan, list[str]]:
    """
    Keeps what passed the checks and puts back the original for the rest, instead of throwing the whole
    tailoring away over one bad rewrite. Returns the cleaned plan and a plain note for each thing skipped.
    Structural problems (a bullet dropped, moved to another role, an unknown id) are not repaired here.
    """
    vocabulary = _words(master_text)
    notes: list[str] = []
    blocks_by_id = {b.id: b for b in blocks}
    for planned in plan.blocks:
        block = blocks_by_id.get(planned.block_id)
        if block is None:
            continue
        original = {b.id: b for b in block.bullets}
        for bullet in planned.bullets:
            if bullet.bullet_id not in original:
                continue
            found = _check_rewrite(bullet.bullet_id, original[bullet.bullet_id].text, bullet.text, vocabulary, firm)
            if found:
                notes.append(f"Kept the original wording of one bullet ({found[0].split(' ', 2)[2]}).")
                bullet.text = original[bullet.bullet_id].text
    by_id = {p.id: p for p in (parts or [])}
    keep_summaries = []
    for planned in plan.summaries:
        part = by_id.get(planned.part_id)
        found = (
            _check_rewrite(
                planned.part_id, part.text, planned.text, vocabulary, firm,
                label="summary", max_growth=MAX_LENGTH_GROWTH_FIRM if firm else MAX_LENGTH_GROWTH_LIGHT,
            )
            if part is not None and part.kind == "summary"
            else ["unknown"]
        )
        if found:
            notes.append(f"Kept your original summary ({found[0].split(' ', 2)[-1]}).")
        else:
            keep_summaries.append(planned)
    plan.summaries = keep_summaries
    keep_skills = []
    for planned in plan.skills:
        part = by_id.get(planned.part_id)
        ok = part is not None and part.kind == "skills" and sorted(i.strip().lower() for i in planned.items) == sorted(
            i.lower() for i in part.items
        )
        if ok:
            keep_skills.append(planned)
        else:
            notes.append("Kept the original order of one skills line (the AI changed its items).")
    plan.skills = keep_skills
    return plan, notes
