"""
Verified-claim generation from structured resume extraction (spec §12).
Not sentence-splitting — each claim is an atomic, source-traceable fact the
rest of the system (resume tailoring, answer generation) is allowed to draw
from. The claims below are produced deterministically from the already-
validated ResumeExtraction structure — the LLM's job was extraction into
that structure (app/services/llm/router.py); turning structured entries
into individual VerifiedClaim rows is plain data transformation, not a
second generative step, so nothing here can introduce a new unsupported
fact that wasn't already in the extraction.
"""

from __future__ import annotations

import datetime as dt

from app.services.llm.schemas import ResumeExtraction


class DraftClaim:
    """Not yet persisted — the onboarding review step (spec §12) lets the
    candidate correct or discard claims before they become VerifiedClaim
    rows tied to a profile_id."""

    def __init__(
        self,
        *,
        category: str,
        canonical_text: str,
        employer: str | None = None,
        associated_role: str | None = None,
        skills: list[str] | None = None,
        start_date: dt.date | None = None,
        end_date: dt.date | None = None,
        metrics: dict | None = None,
        source_section: str,
        source_text: str,
    ) -> None:
        self.category = category
        self.canonical_text = canonical_text
        self.employer = employer
        self.associated_role = associated_role
        self.skills = skills or []
        self.start_date = start_date
        self.end_date = end_date
        self.metrics = metrics or {}
        self.source_section = source_section
        self.source_text = source_text


def parse_partial_date(value: str | None) -> dt.date | None:
    """Resumes give "2021-04", "2021", or full ISO dates. Best-effort parse;
    an unparseable date is left None rather than guessed — a missing date
    is a gap the qualification pipeline can represent as UNKNOWN (spec
    §21), which is honest; a wrong guessed date is a fabricated fact."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            parsed = dt.datetime.strptime(value, fmt)
            return parsed.date()
        except ValueError:
            continue
    return None


# Retained for any existing internal callers within this module.
_parse_partial_date = parse_partial_date


def generate_claims(extraction: ResumeExtraction) -> list[DraftClaim]:
    claims: list[DraftClaim] = []

    for entry in extraction.employment:
        claims.append(
            DraftClaim(
                category="experience",
                canonical_text=f"Worked as {entry.title} at {entry.employer}.",
                employer=entry.employer,
                associated_role=entry.title,
                start_date=_parse_partial_date(entry.start_date),
                end_date=_parse_partial_date(entry.end_date),
                source_section="employment",
                source_text=entry.source_text,
            )
        )

    for skill in extraction.skills:
        claims.append(
            DraftClaim(
                category="skill",
                canonical_text=f"Has experience with {skill}.",
                skills=[skill],
                source_section="skills",
                source_text=skill,
            )
        )

    for edu in extraction.education:
        degree_part = f"{edu.degree} in {edu.field}" if edu.field else (edu.degree or "a degree")
        claims.append(
            DraftClaim(
                category="education",
                canonical_text=f"Earned {degree_part} from {edu.institution}.",
                employer=edu.institution,
                start_date=_parse_partial_date(edu.start_date),
                end_date=_parse_partial_date(edu.end_date),
                source_section="education",
                source_text=f"{edu.institution} — {degree_part}",
            )
        )

    for cert in extraction.certifications:
        claims.append(
            DraftClaim(
                category="certification",
                canonical_text=f"Holds certification: {cert.certification}"
                + (f" (issued by {cert.issuer})" if cert.issuer else ""),
                start_date=_parse_partial_date(cert.date),
                end_date=_parse_partial_date(cert.expiration),
                source_section="certifications",
                source_text=cert.certification,
            )
        )

    for project in extraction.projects:
        text = f"Worked on project: {project.name}."
        if project.description:
            text += f" {project.description}"
        claims.append(
            DraftClaim(
                category="project",
                canonical_text=text,
                skills=project.technologies,
                source_section="projects",
                source_text=project.source_text or project.name,
            )
        )

    return claims
