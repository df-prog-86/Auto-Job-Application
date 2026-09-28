"""
Renders a candidate's stored profile as plain text for the qualification
LLM call to read alongside a job description. Pulls only from the
candidate's own verified profile data (spec §12's source-traceable facts)
-- never anything inferred or supplied by the job itself.
"""

from __future__ import annotations

from app.models.candidate import CandidateProfile


def _date_range(start, end) -> str:
    if start is None and end is None:
        return ""
    start_s = start.isoformat() if start else "?"
    end_s = end.isoformat() if end else "present"
    return f" ({start_s} - {end_s})"


def summarize_candidate(profile: CandidateProfile | None) -> str:
    """
    A compact, readable text block: employment history, education, skills,
    and certifications. Verified claims are folded into employment entries
    where they share an employer, since that's the richest source of detail
    (metrics, responsibilities) about what the candidate actually did.
    """
    if profile is None:
        return ""

    sections: list[str] = []

    if profile.employment_history:
        lines = []
        for entry in profile.employment_history:
            lines.append(f"- {entry.title} at {entry.employer}{_date_range(entry.start_date, entry.end_date)}")
            claims = [
                c.canonical_text
                for c in profile.verified_claims
                if c.employer and c.employer.lower() == entry.employer.lower()
            ]
            for claim in claims:
                lines.append(f"  - {claim}")
        sections.append("Work history:\n" + "\n".join(lines))

    other_claims = [
        c.canonical_text
        for c in profile.verified_claims
        if not (c.employer and any(e.employer.lower() == c.employer.lower() for e in profile.employment_history))
    ]
    if other_claims:
        sections.append("Other verified background:\n" + "\n".join(f"- {c}" for c in other_claims))

    if profile.education:
        lines = [
            f"- {e.degree or ''} {e.field or ''} — {e.institution}{_date_range(e.start_date, e.end_date)}".strip()
            for e in profile.education
        ]
        sections.append("Education:\n" + "\n".join(lines))

    if profile.skills:
        sections.append("Skills: " + ", ".join(s.canonical_skill for s in profile.skills))

    if profile.certifications:
        sections.append("Certifications: " + ", ".join(c.certification for c in profile.certifications))

    return "\n\n".join(sections)
