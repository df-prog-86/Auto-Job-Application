"""
Greenhouse discovery provider (spec §16, §53). Reads the public job-board
API at boards-api.greenhouse.io — the same feed that powers a company's
public boards.greenhouse.io/<token> page. No employer credential involved;
this is read-only, unauthenticated, and exactly what a job seeker's browser
would load.
"""

from __future__ import annotations

import datetime as dt

import httpx

from app.services.discovery.base import DiscoveryProvider, DiscoveryProviderError, RawJobPosting

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"
TIMEOUT_SECONDS = 15.0


class GreenhouseProvider(DiscoveryProvider):
    name = "greenhouse"

    def search(self, identifier: str) -> list[RawJobPosting]:
        url = f"{BASE_URL}/{identifier}/jobs"
        try:
            response = httpx.get(url, params={"content": "true"}, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DiscoveryProviderError(f"Greenhouse request failed for '{identifier}': {exc}") from exc

        payload = response.json()
        postings: list[RawJobPosting] = []
        for job in payload.get("jobs", []):
            location = (job.get("location") or {}).get("name")
            updated_at = _parse_datetime(job.get("updated_at"))
            postings.append(
                RawJobPosting(
                    external_job_id=str(job["id"]),
                    title=job.get("title", ""),
                    company=identifier,
                    location=location,
                    description_html=job.get("content"),
                    application_url=job.get("absolute_url", ""),
                    posted_at=updated_at,
                    extra={"departments": [d.get("name") for d in job.get("departments", [])]},
                )
            )
        return postings

    def health_check(self, identifier: str) -> bool:
        try:
            response = httpx.get(f"{BASE_URL}/{identifier}", timeout=TIMEOUT_SECONDS)
            return response.status_code == 200
        except httpx.HTTPError:
            return False


def _parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
