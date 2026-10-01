"""
Deterministic checks on model-written resume content (spec §26). Pure logic,
no database or LLM access, so it can be tested on its own.

What this enforces: every bullet cites real claims belonging to the right
employer, no number appears that the cited claims don't contain, and every
listed skill already exists in the candidate's own data.

What it can't catch: a model rewording a claim to imply something stronger
without adding any number or new skill. That's why the UI tells the candidate
to read the result before using it, and why the original-wording fallback
exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.llm.schemas import TailoredResumeContent

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_WORD = re.compile(r"[a-z0-9]+")

# Soft rephrase: a bullet must keep most of the words of the claim(s) it cites.
# Anything rewritten more heavily than this is rejected and the retry/fallback
# path keeps the candidate's own wording.
MIN_WORDS_KEPT = 0.6


@dataclass(frozen=True)
class ClaimRef:
    id: int
    text: str
    employer: str | None
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class EmploymentRef:
    id: int
    employer: str
    title: str


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "") for m in _NUMBER.finditer(text)}


def validate_content(
    content: TailoredResumeContent,
    *,
    claims: list[ClaimRef],
    employment: list[EmploymentRef],
    candidate_skills: list[str],
) -> list[str]:
    """Returns a list of problems; empty means the content passed."""
    problems: list[str] = []
    claims_by_id = {c.id: c for c in claims}
    employment_by_id = {e.id: e for e in employment}

    if content.summary:
        if not content.summary_source_claim_ids:
            problems.append("summary cites no claims")
        problems.extend(
            _check_text(content.summary, content.summary_source_claim_ids, claims_by_id, "summary", closeness=False)
        )

    seen_employment: set[int] = set()
    for exp in content.experience:
        job = employment_by_id.get(exp.employment_id)
        if job is None:
            problems.append(f"experience references unknown employment id {exp.employment_id}")
            continue
        if exp.employment_id in seen_employment:
            problems.append(f"employment id {exp.employment_id} appears more than once")
        seen_employment.add(exp.employment_id)

        for bullet in exp.bullets:
            label = f"bullet at {job.employer}"
            if not bullet.source_claim_ids:
                problems.append(f"{label} cites no claims")
                continue
            problems.extend(_check_text(bullet.text, bullet.source_claim_ids, claims_by_id, label))
            for cid in bullet.source_claim_ids:
                claim = claims_by_id.get(cid)
                if claim and claim.employer and claim.employer.strip().lower() != job.employer.strip().lower():
                    problems.append(f"{label} cites a claim from a different employer ({claim.employer})")

    allowed_skills = {s.strip().lower() for s in candidate_skills}
    for claim in claims:
        allowed_skills.update(s.strip().lower() for s in claim.skills)
    for skill in content.skills:
        if skill.strip().lower() not in allowed_skills:
            problems.append(f"skill {skill!r} is not in the candidate's data")

    return problems


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _check_text(
    text: str, claim_ids: list[int], claims_by_id: dict[int, ClaimRef], label: str, closeness: bool = True
) -> list[str]:
    problems: list[str] = []
    missing = [cid for cid in claim_ids if cid not in claims_by_id]
    if missing:
        problems.append(f"{label} cites claim ids that don't exist: {missing}")
        return problems

    allowed_numbers: set[str] = set()
    for cid in claim_ids:
        allowed_numbers |= _numbers(claims_by_id[cid].text)
    introduced = _numbers(text) - allowed_numbers
    if introduced:
        problems.append(f"{label} introduces numbers not in its cited claims: {sorted(introduced)}")

    claim_words: set[str] = set()
    for cid in claim_ids:
        claim_words |= _words(claims_by_id[cid].text)
    if closeness and claim_words:
        kept = len(claim_words & _words(text)) / len(claim_words)
        if kept < MIN_WORDS_KEPT:
            problems.append(f"{label} rewords its cited claims too heavily (keeps {kept:.0%} of their words)")
    return problems


def original_wording_content(
    *, claims: list[ClaimRef], employment: list[EmploymentRef], candidate_skills: list[str]
) -> TailoredResumeContent:
    """
    The safe fallback (spec §26: "or use original candidate wording"): each
    claim becomes a bullet verbatim, grouped under its employer. Claims with
    no matching employer are left out of experience.
    """
    from app.services.llm.schemas import TailoredBullet, TailoredExperience

    experience: list[TailoredExperience] = []
    for job in employment:
        bullets = [
            TailoredBullet(text=c.text, source_claim_ids=[c.id])
            for c in claims
            if c.employer and c.employer.strip().lower() == job.employer.strip().lower()
        ]
        if bullets:
            experience.append(TailoredExperience(employment_id=job.id, bullets=bullets))
    return TailoredResumeContent(experience=experience, skills=list(candidate_skills))
