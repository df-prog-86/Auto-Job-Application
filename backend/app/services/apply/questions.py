"""Helpers shared by the apply and Needs Attention endpoints."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_TRAILING_REQUIRED = re.compile(r"\s+(required|optional)$")


def normalize_question(label: str) -> str:
    """
    Lowercase, strip punctuation (so "Why us? *" and "why us" match), and drop
    a trailing "required"/"optional". MUST stay identical to normalizeQuestion
    in extension/src/form-engine/canonical.ts.
    """
    text = _NON_ALNUM.sub(" ", label.lower()).strip()
    text = _TRAILING_REQUIRED.sub("", text)
    return text.strip()


def answer_key_for(question_key: str) -> str:
    return f"q:{question_key}"[:100]


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    host = parts.netloc.lower()
    # An Ashby posting and its application form are the same job: ".../<id>" and ".../<id>/application".
    if host.endswith("ashbyhq.com") and path.lower().endswith("/application"):
        path = path[: -len("/application")]
    return f"{parts.scheme.lower()}://{host}{path}"


_GH_ID = re.compile(r"(?:/jobs/|[?&](?:gh_jid|token)=)(\d+)")


def greenhouse_job_id(url: str) -> str | None:
    match = _GH_ID.search(url)
    return match.group(1) if match else None


def urls_match(page_url: str, job_url: str) -> bool:
    """Exact (ignoring query, fragment and trailing slash), or the same Greenhouse job id."""
    if normalize_url(page_url) == normalize_url(job_url):
        return True
    page_gh, job_gh = greenhouse_job_id(page_url), greenhouse_job_id(job_url)
    return bool(page_gh and page_gh == job_gh and "greenhouse" in page_url.lower() and "greenhouse" in job_url.lower())
