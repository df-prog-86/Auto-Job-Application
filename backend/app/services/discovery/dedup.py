"""
Deduplication key (spec §20). Preferred order:

1. ATS + external job ID — the strongest signal, when we have both.
2. Normalized canonical application URL.
3. SHA-256(normalized company + normalized title + normalized location) —
   last resort, only when neither of the above is available.

Never Python's runtime hash() for anything persisted — it's salted per
process and would silently break every dedup key on the next restart.
"""

from __future__ import annotations

import hashlib


def compute_canonical_job_key(
    *,
    ats: str | None,
    external_job_id: str | None,
    canonical_application_url: str | None,
    normalized_company: str,
    normalized_title: str,
    normalized_location: str,
) -> str:
    if ats and external_job_id:
        return f"ats:{ats}:{external_job_id}"
    if canonical_application_url:
        return f"url:{canonical_application_url}"
    digest = hashlib.sha256(
        f"{normalized_company}|{normalized_title}|{normalized_location}".encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"
