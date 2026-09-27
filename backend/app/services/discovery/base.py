"""
Provider interface for job discovery (spec §16): every source (Greenhouse,
Lever, and anything added later) implements this same shape so the pipeline
never needs to know which ATS it's talking to.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RawJobPosting:
    """
    What a provider hands back for one posting, before normalization. Fields
    are deliberately close to what each ATS's API returns — normalization
    happens as a separate step (spec §19) so provider code stays a thin,
    honest translation of the source, not a place logic hides.
    """

    external_job_id: str
    title: str
    company: str
    location: str | None
    description_html: str | None
    application_url: str
    posted_at: dt.datetime | None = None
    salary_text: str | None = None
    extra: dict = field(default_factory=dict)


class DiscoveryProviderError(RuntimeError):
    """Raised when a provider can't complete a search or health check."""


class DiscoveryProvider(ABC):
    """Spec §16: search / normalize is split — this covers search+health;
    normalization lives in services/discovery/normalization.py so it's
    shared identically across every provider."""

    name: str

    @abstractmethod
    def search(self, identifier: str) -> list[RawJobPosting]:
        """Fetch all current postings for one employer (by ATS-specific
        identifier — a Greenhouse board token or Lever company slug)."""

    @abstractmethod
    def health_check(self, identifier: str) -> bool:
        """True if this employer's board is reachable and returning data."""
