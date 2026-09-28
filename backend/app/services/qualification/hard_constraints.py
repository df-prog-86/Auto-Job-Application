"""
Stage 1 of the qualification pipeline (spec §21): free, deterministic
PASS/FAIL/UNKNOWN checks, run before any LLM call. Per spec, missing data is
never automatically a failure -- every check below defaults to UNKNOWN
rather than guessing, and only records a FAIL when something concrete
contradicts it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.candidate import CandidateAnswer
from app.models.jobs import Job
from app.models.search import SearchProfile
from app.services.discovery.normalization import normalize_location, normalize_title

ConstraintStatus = str  # "PASS" | "FAIL" | "UNKNOWN"

_SENIORITY_KEYWORDS: list[tuple[str, str]] = [
    ("intern", "intern"),
    ("internship", "intern"),
    ("junior", "junior"),
    ("associate", "associate"),
    ("senior", "senior"),
    ("sr.", "senior"),
    ("staff", "staff"),
    ("principal", "principal"),
    ("lead", "lead"),
    ("director", "director"),
    ("vp", "vp"),
    ("vice president", "vp"),
    ("head of", "director"),
]

_EMPLOYMENT_TYPE_KEYWORDS: list[tuple[str, str]] = [
    ("internship", "internship"),
    ("intern", "internship"),
    ("contract to hire", "contract"),
    ("c2c", "contract"),
    ("contractor", "contract"),
    ("contract", "contract"),
    ("part-time", "part_time"),
    ("part time", "part_time"),
    ("full-time", "full_time"),
    ("full time", "full_time"),
]

_NO_SPONSORSHIP_PHRASES = (
    "not able to sponsor",
    "will not sponsor",
    "no sponsorship",
    "unable to sponsor",
    "does not sponsor",
    "not sponsor visas",
)
_CITIZENSHIP_PHRASES = (
    "u.s. citizenship required",
    "us citizenship required",
    "must be a u.s. citizen",
    "must be a us citizen",
    "citizens only",
)
_CLEARANCE_PHRASES = (
    "security clearance required",
    "active security clearance",
    "must be able to obtain a security clearance",
    "must hold a security clearance",
)


@dataclass
class HardConstraintResult:
    constraints: dict[str, ConstraintStatus] = field(default_factory=dict)
    disqualifiers: list[str] = field(default_factory=list)

    @property
    def overall(self) -> str:
        return "FAIL" if self.disqualifiers else "PASS"


def evaluate_hard_constraints(
    job: Job,
    search_profiles: list[SearchProfile],
    candidate_answers: list[CandidateAnswer],
) -> HardConstraintResult:
    result = HardConstraintResult()
    description = (job.description or "").lower()
    title = job.title.lower()

    _check_excluded(job, search_profiles, result)
    _check_workplace_type(job, search_profiles, result)
    _check_location(job, search_profiles, result)
    _check_salary(job, search_profiles, result)
    _check_employment_type(title, description, search_profiles, result)
    _check_seniority(title, search_profiles, result)
    _check_sponsorship_and_citizenship(description, candidate_answers, result)
    _check_clearance(description, candidate_answers, result)

    return result


def _mark(result: HardConstraintResult, name: str, status: ConstraintStatus) -> None:
    result.constraints[name] = status
    if status == "FAIL":
        result.disqualifiers.append(name)


def _answer_value(answers: list[CandidateAnswer], key: str) -> object | None:
    for answer in answers:
        if answer.answer_key == key:
            return answer.value.get("raw")
    return None


def _check_excluded(job: Job, profiles: list[SearchProfile], result: HardConstraintResult) -> None:
    if not profiles:
        _mark(result, "excluded_employer", "UNKNOWN")
        _mark(result, "excluded_title", "UNKNOWN")
        return

    excluded_employers = {normalize_title(e) for p in profiles for e in p.excluded_employers}
    excluded_titles = {normalize_title(t) for p in profiles for t in p.excluded_titles if t}

    _mark(result, "excluded_employer", "FAIL" if job.normalized_company in excluded_employers else "PASS")
    title_excluded = any(t in job.normalized_title or job.normalized_title in t for t in excluded_titles)
    _mark(result, "excluded_title", "FAIL" if title_excluded else "PASS")


def _check_workplace_type(job: Job, profiles: list[SearchProfile], result: HardConstraintResult) -> None:
    if job.remote_type is None or not profiles:
        _mark(result, "workplace_type", "UNKNOWN")
        return

    accepted = any(
        (job.remote_type == "remote" and p.remote)
        or (job.remote_type == "hybrid" and p.hybrid)
        or (job.remote_type == "onsite" and p.onsite)
        for p in profiles
    )
    _mark(result, "workplace_type", "PASS" if accepted else "FAIL")


def _check_location(job: Job, profiles: list[SearchProfile], result: HardConstraintResult) -> None:
    if job.remote_type == "remote":
        _mark(result, "location", "PASS")
        return
    if not job.location or not profiles:
        _mark(result, "location", "UNKNOWN")
        return

    wanted_locations = {normalize_location(loc) for p in profiles for loc in p.locations}
    if not wanted_locations:
        _mark(result, "location", "PASS")
        return

    normalized_job_location = normalize_location(job.location)
    matched = any(w in normalized_job_location for w in wanted_locations)
    _mark(result, "location", "PASS" if matched else "FAIL")


def _check_salary(job: Job, profiles: list[SearchProfile], result: HardConstraintResult) -> None:
    job_figure = job.salary.get("max") or job.salary.get("min")
    minimums = [p.salary_minimum for p in profiles if p.salary_minimum is not None]
    if job_figure is None or not minimums:
        _mark(result, "salary", "UNKNOWN")
        return
    _mark(result, "salary", "PASS" if job_figure >= min(minimums) else "FAIL")


def _check_employment_type(
    title: str, description: str, profiles: list[SearchProfile], result: HardConstraintResult
) -> None:
    wanted_types = {p.employment_type for p in profiles if p.employment_type}
    if not wanted_types:
        _mark(result, "employment_type", "UNKNOWN")
        return

    haystack = f"{title} {description}"
    detected = next((etype for kw, etype in _EMPLOYMENT_TYPE_KEYWORDS if kw in haystack), None)
    if detected is None:
        _mark(result, "employment_type", "UNKNOWN")
        return
    _mark(result, "employment_type", "PASS" if detected in wanted_types else "FAIL")


def _check_seniority(title: str, profiles: list[SearchProfile], result: HardConstraintResult) -> None:
    wanted_levels = {s.lower() for p in profiles for s in p.desired_seniority}
    if not wanted_levels:
        _mark(result, "seniority", "UNKNOWN")
        return

    detected = next((level for kw, level in _SENIORITY_KEYWORDS if kw in title), None)
    if detected is None:
        _mark(result, "seniority", "UNKNOWN")
        return
    _mark(result, "seniority", "PASS" if detected in wanted_levels else "FAIL")


def _check_sponsorship_and_citizenship(
    description: str, candidate_answers: list[CandidateAnswer], result: HardConstraintResult
) -> None:
    needs_sponsorship = _answer_value(candidate_answers, "sponsorship_required")
    if needs_sponsorship is None:
        _mark(result, "sponsorship", "UNKNOWN")
        return

    blocks_sponsorship = any(p in description for p in _NO_SPONSORSHIP_PHRASES) or any(
        p in description for p in _CITIZENSHIP_PHRASES
    )
    if not blocks_sponsorship:
        _mark(result, "sponsorship", "UNKNOWN")
        return
    _mark(result, "sponsorship", "FAIL" if needs_sponsorship else "PASS")


def _check_clearance(
    description: str, candidate_answers: list[CandidateAnswer], result: HardConstraintResult
) -> None:
    requires_clearance = any(p in description for p in _CLEARANCE_PHRASES)
    if not requires_clearance:
        _mark(result, "clearance", "UNKNOWN")
        return

    candidate_clearance = _answer_value(candidate_answers, "security_clearance")
    if candidate_clearance is None:
        _mark(result, "clearance", "UNKNOWN")
        return
    holds_clearance = bool(candidate_clearance) and str(candidate_clearance).lower() != "none"
    _mark(result, "clearance", "PASS" if holds_clearance else "FAIL")
