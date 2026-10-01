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
from app.services.resume.docx_editor import Block

MIN_WORDS_KEPT = 0.6
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_WORD = re.compile(r"[a-z0-9]+")
_TERM = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#./-]*")


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "") for m in _NUMBER.finditer(text)}


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def validate_plan(plan: TailorPlan, blocks: list[Block], master_text: str) -> list[str]:
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
            problems.extend(_check_rewrite(bullet.bullet_id, original[bullet.bullet_id].text, bullet.text, vocabulary))
    return problems


def _check_rewrite(bullet_id: int, original: str, new: str, vocabulary: set[str]) -> list[str]:
    if new == original:
        return []
    problems: list[str] = []
    label = f"bullet {bullet_id}"

    introduced = _numbers(new) - _numbers(original)
    if introduced:
        problems.append(f"{label} introduces numbers not in the original: {sorted(introduced)}")

    original_words = _words(original)
    if original_words:
        kept = len(original_words & _words(new)) / len(original_words)
        if kept < MIN_WORDS_KEPT:
            problems.append(f"{label} rewords the original too heavily (keeps {kept:.0%} of its words)")

    for index, term in enumerate(_TERM.findall(new)):
        lowered = term.lower()
        if index == 0 or lowered in original_words or lowered in vocabulary:
            continue
        if term[0].isupper() or any(c.isdigit() for c in term):
            problems.append(f"{label} introduces a term not found in the master resume: {term!r}")
    return problems


def plan_to_dict(plan: TailorPlan) -> dict[int, list[tuple[int, str]]]:
    return {p.block_id: [(b.bullet_id, b.text) for b in p.bullets] for p in plan.blocks}
