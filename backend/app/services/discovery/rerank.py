"""
A second opinion on the saved-list matches. The saved lists rank by words in the title and the place, which cannot tell a good
fit from a near miss (0.68 against 0.69). One small AI call reads the candidates' titles, employers and places and scores how
well each fits what was asked; the score is blended with the word-match fit. Only job titles, employers, places and the search
words are sent, never your profile. The answer is remembered, so the same search gives the same order and costs nothing again.
If the AI is not set up or its answer is unusable, the order is left exactly as it was.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.config import settings
from app.services.jobcache.store import JobCache

log = logging.getLogger(__name__)

AI_WEIGHT = 0.6  # share of the blended fit that comes from the AI's score
MAX_CANDIDATES = 100

_PROMPT = (
    "You rank job postings for one job search. For each numbered posting give a score from 0 to 10 for how well it fits what the "
    "searcher asked for. Judge the role first: the same kind of work, field and seniority as the titles asked for (10 = the same "
    "job, 7 = a close alternative title, 4 = related but a different focus or level, 0 = a different job). Then the place: in or "
    "near the place asked for, or remote when remote is fine. A missing place or pay never lowers a score. Reply with ONLY a JSON "
    "array of integers, one per posting, in the same order."
)


def _enabled() -> bool:
    return (getattr(settings, "JOB_SEARCH_RERANK", "on") or "on").lower() != "off"


def _model() -> str | None:
    return settings.JOB_SEARCH_MODEL or settings.PRIMARY_FAST_MODEL


def _ask_text(criteria: Any, items: list[dict[str, Any]]) -> str:
    lines = [f"Searching for: {criteria.titles}", f"Place: {criteria.location or 'anywhere'}", f"Work type: {criteria.work_type}"]
    if getattr(criteria, "keywords", None):
        lines.append(f"Must mention: {criteria.keywords}")
    lines.append("Postings:")
    for n, it in enumerate(items, 1):
        lines.append(f"{n}. {it['title']} | {it['company']} | {(it.get('location') or 'no place')[:60]}")
    return "\n".join(lines)


def parse_scores(text: str, n: int) -> list[float] | None:
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    if not isinstance(data, list) or len(data) != n:
        return None
    out: list[float] = []
    for v in data:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        out.append(max(0.0, min(10.0, float(v))))
    return out


def blend(items: list[dict[str, Any]], scores: list[float]) -> list[dict[str, Any]]:
    for it, s in zip(items, scores):
        it["fit"] = round((1 - AI_WEIGHT) * float(it.get("fit") or 0.0) + AI_WEIGHT * s / 10.0, 4)
    return sorted(items, key=lambda i: -(i.get("fit") or 0.0))  # stable: equal scores keep the word-match order


async def rerank(criteria: Any, items: list[dict[str, Any]], keep: int) -> list[dict[str, Any]]:
    """The `keep` best of `items` after the AI's second opinion; the first `keep` unchanged when no opinion is available."""
    items = items[:MAX_CANDIDATES]
    if len(items) <= 1 or not _enabled():
        return items[:keep]
    model = _model()
    if not model:
        return items[:keep]
    text = _ask_text(criteria, items)
    key = "rerank:" + hashlib.sha1(f"{model}|{text}".encode()).hexdigest()
    scores: list[float] | None = None
    try:
        cache = JobCache()
        saved = cache.meta_get(key)
        if saved is not None:
            scores = parse_scores(saved, len(items))
        if scores is None:
            from app.services.llm.client import LLMClient

            result = await LLMClient().chat_completion(
                model=model,
                messages=[{"role": "system", "content": _PROMPT}, {"role": "user", "content": text}],
                temperature=0.0,
                max_tokens=400,
                timeout=25.0,
            )
            scores = parse_scores(result.content, len(items))
            if scores is not None:
                cache.meta_set(key, json.dumps(scores))
    except Exception:  # a second opinion is a bonus: no answer means the usual order
        log.exception("job search: the AI re-rank failed")
        return items[:keep]
    if scores is None:
        log.warning("job search: the AI re-rank answer was unusable")
        return items[:keep]
    return blend(items, scores)[:keep]
