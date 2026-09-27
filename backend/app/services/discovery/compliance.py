"""
Discovery compliance registry (spec §17). Each source's permissions are
recorded explicitly rather than assumed, and are checked before that source
is ever queried or ever used to submit anything.

Both current sources are read from public, unauthenticated employer job
feeds meant for job seekers to browse — this is what "permitted_for_discovery"
records. Neither source is `permitted_for_application`: spec §53/§297 is
explicit that candidate-side code must not attempt direct application-API
POSTs without employer-granted credentials, so real applications always go
through the browser extension acting like a human on the employer's own
application form, never a scraped API call.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceCompliance:
    source: str
    enabled: bool
    permitted_for_discovery: bool
    permitted_for_application: bool
    requires_auth: bool
    rate_policy: str
    notes: str


SOURCE_REGISTRY: dict[str, SourceCompliance] = {
    "greenhouse": SourceCompliance(
        source="greenhouse",
        enabled=True,
        permitted_for_discovery=True,
        permitted_for_application=False,
        requires_auth=False,
        rate_policy="max 1 request/sec per employer board, sequential across employers",
        notes=(
            "Reads boards-api.greenhouse.io's public job-board feed, the same data "
            "a visitor to boards.greenhouse.io/<token> sees. No employer credential "
            "is used or required. Applications still go through the real form in "
            "the browser (spec §53/§297) — this registry entry covers discovery only."
        ),
    ),
    "lever": SourceCompliance(
        source="lever",
        enabled=True,
        permitted_for_discovery=True,
        permitted_for_application=False,
        requires_auth=False,
        rate_policy="max 1 request/sec per employer board, sequential across employers",
        notes=(
            "Reads api.lever.co's public postings feed, the same data a visitor to "
            "jobs.lever.co/<slug> sees. No employer credential is used or required. "
            "Applications still go through the real form in the browser."
        ),
    ),
    # LinkedIn and Indeed are deliberately absent: scraping their search
    # results violates their Terms of Service. Spec §17 requires production
    # defaults to disable automated application execution on both, and §16
    # treats any such adapter (e.g. JobSpy) as optional and non-core — it is
    # not wired in here. See docs/production-spec-v1.0.md §16-17.
}


def is_permitted_for_discovery(source: str) -> bool:
    entry = SOURCE_REGISTRY.get(source)
    return bool(entry and entry.enabled and entry.permitted_for_discovery)


def is_permitted_for_application(source: str) -> bool:
    entry = SOURCE_REGISTRY.get(source)
    return bool(entry and entry.enabled and entry.permitted_for_application)
