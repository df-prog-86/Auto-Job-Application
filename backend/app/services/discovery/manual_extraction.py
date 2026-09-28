"""
Manual job intake: the user finds a posting themselves (on LinkedIn, Indeed,
a company site, wherever) and hands us either its URL (Option 1 -- we fetch
that one page ourselves) or the already-loaded page content captured by the
browser extension from their own logged-in session (Option 2). Both are a
single, user-directed read of one page the user explicitly chose -- this is
not the automated, repeated per-employer crawling that services/discovery/
compliance.py's SOURCE_REGISTRY governs, so no registry entry is needed here.
It's the same thing a browser does whenever a person visits a link.

Extraction prefers structured data (schema.org JobPosting -- the same markup
Google Jobs itself reads) over the LLM, per spec §7's deterministic-before-
generative principle. The LLM fallback only runs when a page has no
JobPosting markup at all.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.services.discovery.base import RawJobPosting
from app.services.discovery.normalization import html_to_text
from app.services.llm.exceptions import LLMError
from app.services.llm.router import ModelRouter
from app.services.llm.schemas import JobPostingExtraction

_FETCH_TIMEOUT = 15.0
_USER_AGENT = (
    "Mozilla/5.0 (compatible; JobAgent/0.1; a personal job-search tool fetching "
    "a single page at its user's explicit request)"
)
_MAX_BODY_TEXT_CHARS = 12000

_JSONLD_PATTERN = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_PATTERN = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


class ManualExtractionError(RuntimeError):
    """A job posting could not be fetched or extracted from a page."""


@dataclass
class FetchedPage:
    url: str
    json_ld_blocks: list[str]
    body_text: str
    title: str | None = None


async def fetch_page(url: str) -> FetchedPage:
    """
    Server-side fetch for Option 1 (paste-a-URL). Some sites -- notably
    LinkedIn and Indeed -- actively block requests from datacenter IPs even
    for a single-page read; that's a bot-detection wall, not something to
    route around here. If this raises, the caller should point the user at
    the extension capture path (Option 2) instead, which reads the page from
    their own browser and isn't affected by it.
    """
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ManualExtractionError(
                f"Couldn't fetch that page directly ({exc}). Some sites block automated "
                "fetches even for a single page -- try the 'Save this job' button in the "
                "browser extension instead, which reads the page from your own browser."
            ) from exc

    html = resp.text
    return FetchedPage(
        url=url,
        json_ld_blocks=_JSONLD_PATTERN.findall(html),
        body_text=_visible_text(html),
        title=_extract_title(html),
    )


def _extract_title(html: str) -> str | None:
    match = _TITLE_PATTERN.search(html)
    return match.group(1).strip() if match else None


def _visible_text(html: str) -> str:
    cleaned = _SCRIPT_STYLE_PATTERN.sub(" ", html)
    return (html_to_text(cleaned) or "")[:_MAX_BODY_TEXT_CHARS]


def extract_from_structured_data(json_ld_blocks: list[str], page_url: str) -> RawJobPosting | None:
    for block in json_ld_blocks:
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        for item in _flatten_jsonld(data):
            if _is_job_posting(item):
                posting = _posting_from_jsonld(item, page_url)
                if posting is not None:
                    return posting
    return None


def _flatten_jsonld(data: object) -> list[dict]:
    items: list[dict] = []
    candidates = data if isinstance(data, list) else [data]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        items.append(candidate)
        graph = candidate.get("@graph")
        if isinstance(graph, list):
            items.extend(g for g in graph if isinstance(g, dict))
    return items


def _is_job_posting(item: dict) -> bool:
    type_field = item.get("@type")
    if isinstance(type_field, str):
        return type_field == "JobPosting"
    if isinstance(type_field, list):
        return "JobPosting" in type_field
    return False


def _posting_from_jsonld(item: dict, page_url: str) -> RawJobPosting | None:
    title = item.get("title")
    if not title:
        return None

    hiring_org = item.get("hiringOrganization")
    company = hiring_org.get("name") if isinstance(hiring_org, dict) else None
    if not company:
        return None

    identifier = item.get("identifier")
    external_job_id: str | None = None
    if isinstance(identifier, dict):
        raw_id = identifier.get("value")
        external_job_id = str(raw_id) if raw_id else None
    elif isinstance(identifier, str):
        external_job_id = identifier

    description_html = item.get("description")
    apply_url = item.get("directApplyLink") or item.get("url") or page_url

    return RawJobPosting(
        external_job_id=external_job_id,
        title=str(title),
        company=str(company),
        location=_location_from_jsonld(item),
        description_html=str(description_html) if description_html else None,
        application_url=str(apply_url),
    )


def _location_from_jsonld(item: dict) -> str | None:
    if item.get("jobLocationType") == "TELECOMMUTE" and not item.get("jobLocation"):
        return "Remote"

    job_location = item.get("jobLocation")
    locations = job_location if isinstance(job_location, list) else [job_location]
    parts: list[str] = []
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        address = loc.get("address")
        if not isinstance(address, dict):
            continue
        piece = ", ".join(
            filter(None, [address.get("addressLocality"), address.get("addressRegion")])
        )
        if piece:
            parts.append(piece)
    return "; ".join(parts) if parts else None


async def extract_job_posting(
    db: Session,
    *,
    url: str,
    json_ld_blocks: list[str],
    body_text: str,
    page_title: str | None,
) -> RawJobPosting:
    """Structured data first; the LLM only ever fills in for a page with no
    JobPosting markup at all (spec §7)."""
    structured = extract_from_structured_data(json_ld_blocks, url)
    if structured is not None:
        return structured

    if not body_text.strip():
        raise ManualExtractionError(
            "Couldn't find any readable job content on that page, and it has no "
            "structured job data either -- there may not be enough here to extract from."
        )

    router = ModelRouter(db)
    messages = [
        {
            "role": "system",
            "content": (
                "You extract a single job posting's details from a web page's visible "
                "text. Return ONLY JSON matching the provided schema. Use the job "
                "description text verbatim from the source -- do not summarize or "
                "paraphrase it. Never invent a title, company, or details not present "
                "in the text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Page title: {page_title or '(unknown)'}\n\n"
                f"Page text:\n---\n{body_text}\n---"
            ),
        },
    ]
    try:
        extraction = await router.get_structured(
            purpose="manual_job_extraction",
            prompt_version="v1",
            messages=messages,
            response_model=JobPostingExtraction,
        )
    except LLMError as exc:
        raise ManualExtractionError(
            f"Couldn't automatically read a job posting off that page ({exc}). No LLM "
            "provider may be configured, or the page didn't look like a job posting."
        ) from exc

    return RawJobPosting(
        external_job_id=None,
        title=extraction.title,
        company=extraction.company,
        location=extraction.location,
        description_html=extraction.description,
        application_url=url,
        salary_text=extraction.salary_text,
    )
