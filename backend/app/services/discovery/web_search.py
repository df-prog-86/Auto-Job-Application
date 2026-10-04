"""
Job search across the open web, through the same LLM connection that scores and
tailors (OpenRouter's built-in web search plugin).

Nothing the model says is trusted blindly: a result needs a real http(s) link, and
links the search engine itself returned are marked "grounded". Results are only
suggestions; a job is added to the list when the person clicks Add.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from app.config import settings
from app.schemas.job_search import JobSearchIn
from app.services.discovery.normalization import strip_tracking_params
from app.services.llm.client import LLMClient
from app.services.llm.exceptions import LLMNotConfiguredError

WORK_TYPES = {"remote", "hybrid", "onsite"}


class JobSearchError(RuntimeError):
    """The search could not be completed; the message is safe to show."""


def url_key(url: str) -> str:
    """host + path (no scheme, query, fragment or trailing slash): two spellings of one posting match."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}".lower()


def is_http_url(url: str) -> bool:
    parts = urlsplit(url.strip())
    return parts.scheme in ("http", "https") and "." in parts.netloc


def build_messages(criteria: JobSearchIn) -> list[dict[str, str]]:
    wanted = [f"Job title or role: {criteria.titles}"]
    if criteria.location:
        wanted.append(f"Location: {criteria.location}")
    if criteria.work_type != "any":
        wanted.append(f"Work type: {criteria.work_type} only")
    if criteria.keywords:
        wanted.append(f"Must relate to: {criteria.keywords}")
    if criteria.target_salary:
        low, high = int(criteria.target_salary * 0.85), int(criteria.target_salary * 1.15)
        wanted.append(
            f"Yearly pay where the midpoint of the posted pay range is about ${criteria.target_salary:,} "
            f"(roughly ${low:,} to ${high:,}); postings that state no pay may still be included unless told otherwise below"
        )
    if criteria.require_salary:
        wanted.append("Ignore any posting that does not state its pay or pay range; every result must show pay")
    if criteria.posted_within_days:
        wanted.append(f"Posted within the last {criteria.posted_within_days} days")
    system = (
        "You find job postings that are open right now, using web search. "
        "HARD REQUIREMENT: only recommend a job that is live and accepting applications today. "
        "Open the posting page and confirm it before including it. Exclude any posting that says it is closed, "
        "expired, filled, no longer available or no longer accepting applications, that shows no apply option, "
        "or that redirects to a general careers page or a search page. If you cannot confirm a posting is live, leave it out. "
        "Prefer the employer's own careers page or its applicant-tracking page (Workday, Greenhouse, Lever, Ashby, iCIMS) "
        "over job-board listing pages. Skip duplicate postings. "
        "Never invent a posting, company or link: every item must come from a page you found. "
        "If you find fewer than requested, return fewer; if you find none, return an empty list. "
        "Reply with ONLY a JSON array, no other text. Each item has exactly these keys: "
        '"title", "company", "location" (or null), "work_type" ("remote", "hybrid", "onsite" or "unknown"), '
        '"salary" (text from the posting, or null), "url" (direct link to that posting), '
        '"summary" (one or two plain sentences taken from the posting, no hype).'
    )
    user = f"Find up to {criteria.count} current job postings that match:\n" + "\n".join(f"- {w}" for w in wanted)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_items(text: str) -> list[dict[str, Any]]:
    """The model's answer as a list of objects. Tolerates code fences and a short lead-in."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def cited_urls(raw: dict[str, Any]) -> set[str]:
    """Keys of the links the search engine itself returned (url_citation annotations)."""
    keys: set[str] = set()
    try:
        annotations = raw["choices"][0]["message"].get("annotations") or []
    except (KeyError, IndexError, AttributeError, TypeError):
        return keys
    for a in annotations:
        if isinstance(a, dict) and a.get("type") == "url_citation":
            cite = a.get("url_citation") or {}
            if isinstance(cite, dict) and isinstance(cite.get("url"), str) and is_http_url(cite["url"]):
                keys.add(url_key(cite["url"]))
    return keys


def _clean(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text[:limit] if text else None


async def search_jobs(criteria: JobSearchIn) -> list[dict[str, Any]]:
    """Runs one web search and returns cleaned candidate postings (not yet saved anywhere)."""
    model = settings.PRIMARY_FAST_MODEL
    if not model:
        raise LLMNotConfiguredError("No LLM provider configured (PRIMARY_FAST_MODEL unset).")
    result = await LLMClient().chat_completion(
        model=model,
        messages=build_messages(criteria),
        temperature=0.0,
        max_tokens=4000,
        extra={"plugins": [{"id": "web", "max_results": max(5, min(criteria.count, 15))}]},
        timeout=150.0,
    )
    grounded_keys = cited_urls(result.raw)
    items: list[dict[str, Any]] = []
    for raw_item in parse_items(result.content):
        title = _clean(raw_item.get("title"), 300)
        company = _clean(raw_item.get("company"), 300)
        link = _clean(raw_item.get("url"), 1000)
        if not title or not company or not link or not is_http_url(link):
            continue
        link = strip_tracking_params(link)
        if criteria.require_salary and not _clean(raw_item.get("salary"), 200):
            continue  # the person asked to see only postings that state pay
        work_type = _clean(raw_item.get("work_type"), 30)
        work_type = work_type.lower() if work_type and work_type.lower() in WORK_TYPES else None
        items.append(
            {
                "title": title,
                "company": company,
                "location": _clean(raw_item.get("location"), 300),
                "work_type": work_type,
                "salary_text": _clean(raw_item.get("salary"), 200),
                "summary": _clean(raw_item.get("summary"), 800),
                "url": link,
                "url_key": url_key(link),
                "grounded": url_key(link) in grounded_keys,
            }
        )
    return items
