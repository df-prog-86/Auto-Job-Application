"""
Discovery run orchestration (spec §16-20): for every enabled watched
employer, fetch current postings, normalize them, keep only what an enabled
search profile would actually want, and upsert into the Jobs table by the
dedup key — new jobs are created, previously-seen jobs get last_seen bumped
and gain an additional JobSource if this run found them somewhere new.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.discovery import TargetEmployer
from app.models.jobs import Job, JobSource
from app.models.search import SearchProfile
from app.services.discovery.base import DiscoveryProvider, DiscoveryProviderError, RawJobPosting
from app.services.discovery.compliance import is_permitted_for_discovery
from app.services.discovery.dedup import compute_canonical_job_key
from app.services.discovery.greenhouse import GreenhouseProvider
from app.services.discovery.lever import LeverProvider
from app.services.discovery.matching import matches_any_search_profile
from app.services.discovery.normalization import (
    compute_description_hash,
    detect_remote_type,
    html_to_text,
    normalize_company,
    normalize_location,
    normalize_title,
    parse_salary,
    strip_tracking_params,
)

PROVIDERS: dict[str, DiscoveryProvider] = {
    "greenhouse": GreenhouseProvider(),
    "lever": LeverProvider(),
}


@dataclass
class DiscoveryRunResult:
    employers_checked: int = 0
    employers_failed: int = 0
    postings_fetched: int = 0
    postings_matched: int = 0
    jobs_created: int = 0
    jobs_updated: int = 0
    errors: list[str] = field(default_factory=list)


def run_discovery(db: Session) -> DiscoveryRunResult:
    result = DiscoveryRunResult()

    search_profiles = db.query(SearchProfile).filter(SearchProfile.enabled.is_(True)).all()
    if not search_profiles:
        result.errors.append(
            "No enabled search profile exists — discovery has nothing to match against, "
            "so no jobs were fetched. Create a search profile first."
        )
        return result

    employers = db.query(TargetEmployer).filter(TargetEmployer.enabled.is_(True)).all()

    for employer in employers:
        if not is_permitted_for_discovery(employer.ats):
            result.errors.append(f"{employer.name}: source '{employer.ats}' is not permitted for discovery, skipped.")
            continue

        provider = PROVIDERS.get(employer.ats)
        if provider is None:
            result.errors.append(f"{employer.name}: no provider registered for ATS '{employer.ats}', skipped.")
            continue

        result.employers_checked += 1
        now = dt.datetime.now(dt.UTC)
        try:
            postings = provider.search(employer.identifier)
        except DiscoveryProviderError as exc:
            result.employers_failed += 1
            result.errors.append(str(exc))
            employer.last_checked_at = now
            employer.last_check_status = "error"
            employer.last_check_error = str(exc)[:500]
            continue

        employer.last_checked_at = now
        employer.last_check_status = "ok"
        employer.last_check_error = None
        result.postings_fetched += len(postings)

        for posting in postings:
            _ingest_posting(db, posting, employer, search_profiles, result)

    db.commit()
    return result


def _ingest_posting(
    db: Session,
    posting: RawJobPosting,
    employer: TargetEmployer,
    search_profiles: list[SearchProfile],
    result: DiscoveryRunResult,
) -> None:
    description_text = html_to_text(posting.description_html)
    normalized_company = normalize_company(posting.company)
    normalized_title = normalize_title(posting.title)
    normalized_location = normalize_location(posting.location)
    remote_type = detect_remote_type(posting.location, posting.title, description_text)

    if not matches_any_search_profile(
        search_profiles,
        normalized_title=normalized_title,
        normalized_company=normalized_company,
        normalized_location=normalized_location,
        remote_type=remote_type,
        description_text=description_text,
    ):
        return

    result.postings_matched += 1
    canonical_url = strip_tracking_params(posting.application_url)
    canonical_key = compute_canonical_job_key(
        ats=employer.ats,
        external_job_id=posting.external_job_id,
        canonical_application_url=canonical_url,
        normalized_company=normalized_company,
        normalized_title=normalized_title,
        normalized_location=normalized_location,
    )

    now = dt.datetime.now(dt.UTC)
    job = db.query(Job).filter(Job.canonical_job_key == canonical_key).first()

    if job is None:
        job = Job(
            canonical_job_key=canonical_key,
            ats=employer.ats,
            external_job_id=posting.external_job_id,
            company=posting.company,
            normalized_company=normalized_company,
            title=posting.title,
            normalized_title=normalized_title,
            location=posting.location,
            remote_type=remote_type,
            salary={},
            description=description_text,
            description_hash=compute_description_hash(description_text),
            canonical_application_url=canonical_url,
            first_seen=now,
            last_seen=now,
            status="open",
        )
        db.add(job)
        db.flush()
        db.add(
            JobSource(
                job_id=job.id,
                provider=employer.ats,
                source_url=canonical_url,
                discovered_at=now,
                external_source_id=posting.external_job_id,
            )
        )
        result.jobs_created += 1
        return

    job.last_seen = now
    new_hash = compute_description_hash(description_text)
    if new_hash and new_hash != job.description_hash:
        job.description = description_text
        job.description_hash = new_hash
    already_sourced = any(s.provider == employer.ats for s in job.sources)
    if not already_sourced:
        db.add(
            JobSource(
                job_id=job.id,
                provider=employer.ats,
                source_url=canonical_url,
                discovered_at=now,
                external_source_id=posting.external_job_id,
            )
        )
    result.jobs_updated += 1


def ingest_manual_posting(db: Session, posting: RawJobPosting, *, source_label: str) -> tuple[Job, bool]:
    """
    A single job the user explicitly submitted (pasted URL or extension
    capture -- app/services/discovery/manual_extraction.py), not one an
    automated per-employer crawl found. Reuses the exact same normalization,
    salary-parsing, and dedup logic as run_discovery() above so a manually
    added job behaves identically to a discovered one from qualification
    onward -- there is deliberately no search-profile matching step here,
    since the user already chose this posting themselves.

    Returns (job, created): created is False when the same posting was
    already in the list, so the UI can say so instead of silently showing a
    job that looks newly added.
    """
    description_text = html_to_text(posting.description_html)
    normalized_company = normalize_company(posting.company)
    normalized_title = normalize_title(posting.title)
    normalized_location = normalize_location(posting.location)
    remote_type = detect_remote_type(posting.location, posting.title, description_text)

    canonical_url = strip_tracking_params(posting.application_url)
    canonical_key = compute_canonical_job_key(
        ats=None,
        external_job_id=None,
        canonical_application_url=canonical_url,
        normalized_company=normalized_company,
        normalized_title=normalized_title,
        normalized_location=normalized_location,
    )

    now = dt.datetime.now(dt.UTC)
    job = db.query(Job).filter(Job.canonical_job_key == canonical_key).first()
    created = job is None

    if job is None:
        job = Job(
            canonical_job_key=canonical_key,
            ats=None,
            external_job_id=None,
            company=posting.company,
            normalized_company=normalized_company,
            title=posting.title,
            normalized_title=normalized_title,
            location=posting.location,
            remote_type=remote_type,
            salary=parse_salary(posting.salary_text or description_text),
            posted_at=posting.posted_at.date() if posting.posted_at else None,
            description=description_text,
            description_hash=compute_description_hash(description_text),
            canonical_application_url=canonical_url,
            first_seen=now,
            last_seen=now,
            status="open",
        )
        db.add(job)
        db.flush()
        db.add(
            JobSource(
                job_id=job.id,
                provider=source_label,
                source_url=canonical_url,
                discovered_at=now,
                external_source_id=None,
            )
        )
    else:
        job.last_seen = now
        if job.posted_at is None and posting.posted_at:
            job.posted_at = posting.posted_at.date()
        new_hash = compute_description_hash(description_text)
        if new_hash and new_hash != job.description_hash:
            job.description = description_text
            job.description_hash = new_hash
        if not any(s.provider == source_label for s in job.sources):
            db.add(
                JobSource(
                    job_id=job.id,
                    provider=source_label,
                    source_url=canonical_url,
                    discovered_at=now,
                    external_source_id=None,
                )
            )

    db.commit()
    return job, created
