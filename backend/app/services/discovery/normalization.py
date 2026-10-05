"""
Job normalization (spec §19): turns provider-specific raw postings into the
consistent shape the rest of the system (dedup, qualification, tailoring)
relies on. Every function here is pure and independently testable — no
network, no database.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

_COMPANY_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|plc|gmbh)\.?\b",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Query params that only carry tracking/attribution, never identify the
# posting itself — safe to strip when building the canonical URL (spec §19).
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gh_src", "gh_jid", "lever-source", "lever-origin", "ref", "source",
    "fbclid", "gclid",
}

_REMOTE_KEYWORDS = ("remote", "work from home", "wfh", "distributed", "anywhere")
_HYBRID_KEYWORDS = ("hybrid",)
_ONSITE_KEYWORDS = ("on-site", "onsite", "in-office", "in office")


def normalize_company(name: str) -> str:
    """'Acme, Inc.' and 'ACME' both normalize to 'acme'."""
    lowered = _COMPANY_SUFFIXES.sub("", name.lower())
    return _NON_ALNUM.sub(" ", lowered).strip()


def normalize_title(title: str) -> str:
    return _NON_ALNUM.sub(" ", title.lower()).strip()


def normalize_location(location: str | None) -> str:
    if not location:
        return ""
    return _NON_ALNUM.sub(" ", location.lower()).strip()


def detect_remote_type(location: str | None, title: str | None = None, description: str | None = None) -> str | None:
    """
    Best-effort classification into remote/hybrid/onsite from whatever text
    is available. Returns None when there's no signal either way — callers
    should treat that as "unknown", not "onsite" (spec doesn't allow us to
    guess a candidate out of remote-only postings on missing data).
    """
    haystack = " ".join(filter(None, [location, title, description])).lower()
    if any(kw in haystack for kw in _HYBRID_KEYWORDS):
        return "hybrid"
    if any(kw in haystack for kw in _REMOTE_KEYWORDS):
        return "remote"
    if any(kw in haystack for kw in _ONSITE_KEYWORDS):
        return "onsite"
    return None


def strip_tracking_params(url: str) -> str:
    """Removes known tracking params from a URL, leaving everything else
    (including params that might disambiguate the posting) intact."""
    if not url:
        return url
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _TRACKING_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))


class _TextExtractor(HTMLParser):
    """Minimal HTML -> plain text; avoids pulling in a new dependency for
    what's just stripping tags from ATS-provided job description HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def html_to_text(html: str | None) -> str | None:
    if not html:
        return None
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()


def compute_description_hash(description: str | None) -> str | None:
    if not description:
        return None
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


_SALARY_PATTERN = re.compile(
    r"\$\s?(\d{2,3}(?:,\d{3})?(?:\.\d+)?)\s?(?:k)?"
    r"(?:\s?[-–—to]+\s?\$?\s?(\d{2,3}(?:,\d{3})?(?:\.\d+)?)\s?(?:k)?)?",
    re.IGNORECASE,
)


def parse_posted_date(value: object) -> dt.date | None:
    """A posting date from "2026-09-30" or a full ISO timestamp. None if unreadable or in the future."""
    if not isinstance(value, str):
        return None
    match = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        return None
    try:
        day = dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return day if day <= dt.date.today() else None


def parse_salary(text: str | None) -> dict:
    """
    Best-effort extraction of a salary range from free text. Returns {} when
    nothing parseable is found — this is a convenience for filtering/display,
    never treated as authoritative (the posting text remains the source of
    truth, per the deterministic-before-generative principle).
    """
    if not text:
        return {}
    match = _SALARY_PATTERN.search(text)
    if not match:
        return {}

    def to_number(raw: str | None) -> float | None:
        if raw is None:
            return None
        value = float(raw.replace(",", ""))
        # Treat bare 2-3 digit numbers followed by "k" contextually (e.g. "120k") as thousands.
        if value < 1000 and "k" in text[match.start():match.end()].lower():
            value *= 1000
        return value

    low = to_number(match.group(1))
    high = to_number(match.group(2)) if match.group(2) else None
    result: dict = {"currency": "USD", "period": "year" if "hr" not in text.lower() and "hour" not in text.lower() else "hour"}
    if low is not None:
        result["min"] = low
    if high is not None:
        result["max"] = high
    return result if ("min" in result or "max" in result) else {}
