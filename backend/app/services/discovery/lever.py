"""
Lever discovery provider (spec §16, §53). Reads the public postings API at
api.lever.co — the same feed that powers a company's public
jobs.lever.co/<slug> page. No employer credential involved.
"""

from __future__ import annotations

import datetime as dt

import httpx

from app.services.discovery.base import DiscoveryProvider, DiscoveryProviderError, RawJobPosting

BASE_URL = "https://api.lever.co/v0/postings"
TIMEOUT_SECONDS = 15.0


class LeverProvider(DiscoveryProvider):
    name = "lever"

    def search(self, identifier: str) -> list[RawJobPosting]:
        url = f"{BASE_URL}/{identifier}"
        try:
            response = httpx.get(url, params={"mode": "json"}, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DiscoveryProviderError(f"Lever request failed for '{identifier}': {exc}") from exc

        postings: list[RawJobPosting] = []
        for job in response.json():
            categories = job.get("categories") or {}
            posted_at = _parse_epoch_millis(job.get("createdAt"))
            postings.append(
                RawJobPosting(
                    external_job_id=str(job["id"]),
                    title=job.get("text", ""),
                    company=identifier,
                    location=categories.get("location"),
                    description_html=job.get("description") or job.get("descriptionPlain"),
                    application_url=job.get("hostedUrl") or job.get("applyUrl") or "",
                    posted_at=posted_at,
                    extra={"team": categories.get("team"), "commitment": categories.get("commitment")},
                )
            )
        return postings

    def health_check(self, identifier: str) -> bool:
        try:
            response = httpx.get(f"{BASE_URL}/{identifier}", params={"mode": "json"}, timeout=TIMEOUT_SECONDS)
            return response.status_code == 200
        except httpx.HTTPError:
            return False


def _parse_epoch_millis(value: int | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromtimestamp(value / 1000, tz=dt.UTC)
    except (ValueError, OSError):
        return None
