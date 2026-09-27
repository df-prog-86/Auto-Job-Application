"""
Search-profile matching: a coarse, deterministic filter applied at discovery
time (spec §4.3) so only postings a candidate could plausibly want get
stored at all. This is intentionally cheap and keyword-based — the real
qualification scoring (hard filters, coverage, alignment) is Milestone 4's
job and runs on stored jobs afterward. This step just keeps the jobs table
from filling with postings no enabled search profile would ever match.
"""

from __future__ import annotations

from app.models.search import SearchProfile
from app.services.discovery.normalization import normalize_location, normalize_title


def matches_search_profile(
    profile: SearchProfile,
    *,
    normalized_title: str,
    normalized_company: str,
    normalized_location: str,
    remote_type: str | None,
    description_text: str | None,
) -> bool:
    if not profile.enabled:
        return False

    if any(normalize_title(t) == normalized_title or normalize_title(t) in normalized_title for t in profile.excluded_titles):
        return False
    if normalized_company in {normalize_title(c) for c in profile.excluded_employers}:
        return False

    if profile.titles:
        wanted_titles = {normalize_title(t) for t in profile.titles}
        if not any(w in normalized_title or normalized_title in w for w in wanted_titles):
            return False

    if profile.locations and remote_type != "remote":
        wanted_locations = {normalize_location(loc) for loc in profile.locations}
        if not any(w in normalized_location for w in wanted_locations):
            return False

    if remote_type == "remote" and not profile.remote:
        return False
    if remote_type == "hybrid" and not profile.hybrid:
        return False
    if remote_type == "onsite" and not profile.onsite:
        return False

    if profile.required_keywords:
        haystack = f"{normalized_title} {description_text or ''}".lower()
        if not all(kw.lower() in haystack for kw in profile.required_keywords):
            return False

    return True


def matches_any_search_profile(profiles: list[SearchProfile], **kwargs) -> bool:
    return any(matches_search_profile(p, **kwargs) for p in profiles)
