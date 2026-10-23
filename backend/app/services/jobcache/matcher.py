"""
Finds and ranks the best matches for a search in the saved job lists, using plain code (no AI per posting).

A search is turned into a plan: the job titles wanted (plus a few alternative titles for the same kind of work), the
place, work type, pay floor and date window. The full-text index narrows thousands of postings to a few hundred
candidates, and each candidate is scored on how well its title matches, how well its place fits, how recent it is, and
whether its pay is known and acceptable. Titles that only share a word with the search are dropped.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.jobcache.text import (
    SENIORITY_ONLY,
    STATE_BY_NAME,
    STOPWORDS,
    LocationQuery,
    title_names_foreign,
    all_stems,
    content_stems,
    effective_work_type,
    name_excluded,
    fold,
    is_vague_place,
    level_of,
    location_fit,
    parse_location_query,
    pay_midpoint,
    place_ref,
    split_titles,
    words,
)

MIN_TITLE_FIT = 0.35  # below this a title only shares a word or two with the search: left out
CANDIDATE_LIMIT = 5000  # postings read from the index per search: high enough that every real match is reached, low enough to stay fast
EXPANDED_WEIGHT = 0.85  # an alternative title counts for a little less than the one the person typed
OTHER_FIELD_WEIGHT = 0.72  # ...and one that names none of the kind of work typed counts for clearly less
SHORT_OTHER_FIELD_WEIGHT = 0.55  # an alternative to a two-word title ("financial analyst") that drops the field word: shown, but never a strong match
LOOKALIKE_WEIGHT = 0.30 # ...and one that names only PART of it ("revenue operations" for "revenue cycle") is usually a different field

STALE_DAYS = 180
STALE_FACTOR = 0.85

# Stricter ranking (settings.JOB_SEARCH_STRICT_SCORING). `STRICT_OVERRIDE` lets a test or the before-and-after script switch it either way.
STRICT_OVERRIDE: bool | None = None
HIDE_AFTER_DAYS = 90  # strict: older postings are not shown
DESC_ONLY_CAP = 0.50  # strict: a job found only through its description ranks as "Possible" at best (below 55)
DIRECTOR_LEVEL = 5  # strict: a director or above when no level was asked for loses a little
DESC_OTHER_WORK = 0.9  # strict: a good title whose description is about something else is marked down a little


def strict() -> bool:
    if STRICT_OVERRIDE is not None:
        return STRICT_OVERRIDE
    from app.config import settings

    return bool(getattr(settings, "JOB_SEARCH_STRICT_SCORING", False))

W_TITLE, W_PLACE, W_RECENT, W_PAY, W_KEYWORD = 0.62, 0.22, 0.08, 0.04, 0.04
W_DESC = 0.05  # added when the opening of the description names the kind of work asked for; the total is capped at 1
DESC_TITLE_FLOOR = 0.40  # the title credit of a posting found only through its description: above the cut-off, below a real title match
DESC_CHARS = 2000  # how much of the opening of a description is read
DESC_CANDIDATE_LIMIT = 600  # postings added from the description index per search


@dataclass
class TitleQuery:
    raw: str
    stems: list[str]
    terms: list[str]  # the words as written (shorthand expanded), for the full-text index
    level: int | None
    weight: float = 1.0


@dataclass
class Plan:
    queries: list[TitleQuery]
    loc: LocationQuery
    work_type: str = "any"
    keywords: list[str] = field(default_factory=list)  # stems
    keyword_phrases: list[list[str]] = field(default_factory=list)  # one list of stems per keyword the person typed
    pay_floor: int | None = None
    window_days: int = 0
    excluded: list[str] = field(default_factory=list)
    # (the kind of work as stems, the role word) for each asked title with three or more words: "revenue cycle", "analyst".
    desc_phrases: list[tuple[list[str], str]] = field(default_factory=list)

    def earliest(self, today: dt.date | None = None) -> dt.date | None:
        return (today or dt.date.today()) - dt.timedelta(days=self.window_days) if self.window_days else None


def make_query(title: str, weight: float = 1.0) -> TitleQuery | None:
    stems = content_stems(title)
    if not stems:
        return None
    terms = [w for w in words(title) if w not in STOPWORDS and w not in SENIORITY_ONLY]
    return TitleQuery(raw=title, stems=stems, terms=terms, level=level_of(title), weight=weight)


def build_plan(criteria: Any, extra_titles: list[str] | None = None, extra_places: list[str] | None = None) -> Plan:
    """`criteria` is a JobSearchIn (read by attribute so tests can pass any object with the same fields)."""
    queries: list[TitleQuery] = []
    seen: set[str] = set()
    for title in split_titles(criteria.titles):
        q = make_query(title)
        if q and fold(title) not in seen:
            seen.add(fold(title))
            queries.append(q)
    # The kind of work in a specific title ("revenue cycle" in "revenue cycle analyst"). An alternative that has none of it ("Financial
    # Analyst") is the same role word in another field, so it counts for less than a title that names the work itself.
    domain = {s for q in queries if len(q.stems) >= 3 for s in q.stems[:-1]}
    short_domain = {s for q in queries if len(q.stems) == 2 for s in q.stems[:-1]}  # "financial" in "financial analyst"
    for title in extra_titles or []:
        q = make_query(title, EXPANDED_WEIGHT)
        if q and len(q.stems) < 2:
            continue  # a one-word alternative ("Specialist", "Analyst") would match almost any job in the field
        shared = (set(q.stems) & domain) if q else set()
        if q and domain and not shared:
            q.weight = OTHER_FIELD_WEIGHT
        elif q and len(domain) >= 2 and shared and not domain <= set(q.stems):
            q.weight = LOOKALIKE_WEIGHT  # it borrows one word of the kind of work and drops the other: a look-alike, not an alternative
        elif q and not domain and short_domain and not (set(q.stems) & short_domain):
            q.weight = SHORT_OTHER_FIELD_WEIGHT  # "Security Analyst" for "financial analyst": the role word without the field
        if q and fold(title) not in seen:
            seen.add(fold(title))
            queries.append(q)
    keywords = [s for s in content_stems(criteria.keywords) if s] if getattr(criteria, "keywords", None) else []
    phrases = [ph for ph in (content_stems(k) for k in re.split(r"[,;\n]", getattr(criteria, "keywords", None) or "")) if ph]
    floor = None
    if getattr(criteria, "target_salary", None):
        floor = int(criteria.target_salary * 0.95)  # same 5% slack the rest of Job Search uses
    excluded = [e.strip().lower() for e in re.split(r"[,;\n]", getattr(criteria, "exclude_companies", None) or "") if e.strip()][:20]
    desc_phrases: list[tuple[list[str], str]] = []
    if _use_description():
        for q in queries:
            if len(q.stems) >= 3:  # "revenue cycle analyst" (the kind of work is two words); a short title would match far too much
                item = (q.stems[:-1], q.stems[-1])
                if item not in desc_phrases:
                    desc_phrases.append(item)
    loc = parse_location_query(getattr(criteria, "location", None))
    if loc.cities or loc.states:
        # "Any" work type brings remote jobs in after the jobs in the place and its area; Hybrid and On site never show remote jobs, and Remote shows only them
        loc.remote = getattr(criteria, "work_type", "any") in (None, "any") or bool(getattr(criteria, "include_remote", False))
    if loc.cities:  # nearby places only widen a search that names a city
        loc.near = [r for r in (place_ref(p) for p in extra_places or []) if r][:15]
    return Plan(
        queries=queries,
        loc=loc,
        work_type=getattr(criteria, "work_type", "any") or "any",
        keywords=keywords,
        keyword_phrases=phrases,
        pay_floor=floor,
        window_days=int(getattr(criteria, "posted_within_days", 0) or 0),
        excluded=excluded,
        desc_phrases=desc_phrases,
    )


def _use_description() -> bool:
    """The switch for reading descriptions (JOB_SEARCH_USE_DESCRIPTION, on by default), so a before and after test is possible."""
    from app.config import settings

    return bool(getattr(settings, "JOB_SEARCH_USE_DESCRIPTION", True))


def fts_desc_query(plan: Plan) -> str | None:
    """A full-text query for the description index: the kind of work as an exact phrase, for each asked title. None when there is none."""
    parts = []
    for domain, _head in plan.desc_phrases:
        if all(re.fullmatch(r"[a-z0-9]+", t) for t in domain):
            parts.append('"' + " ".join(domain) + '"')
    return " OR ".join(dict.fromkeys(parts)) or None


def desc_hit(plan: Plan, description: str | None, title_stems: set[str] | None = None) -> bool:
    """
    True when the opening of the description names the kind of work asked for ("revenue cycle") as consecutive words. With
    `title_stems`, the title must also hold the role word of that same asked title ("analyst"), so a software engineer whose
    description mentions revenue cycle does not count for a revenue cycle analyst search.
    """
    if not description or not plan.desc_phrases:
        return False
    lead = content_stems(description[:DESC_CHARS])
    return any(
        _contiguous(domain, lead) and (title_stems is None or head in title_stems)
        for domain, head in plan.desc_phrases
    )


ENOUGH_TIGHT = 150  # if the tight query finds this many, the broad one is not needed


def fts_queries(plan: Plan) -> list[str]:
    """
    Full-text queries from tight to broad, all on the title only. Tight: every word of a title (any order); this is
    tiny and instant even on a huge copy. Broad: any word, ranked by the index; used only when the tight query finds
    too few, so a search that has plenty of exact matches never pays for it.
    """
    tight: list[str] = []
    for q in plan.queries:
        terms = [t for t in dict.fromkeys(q.terms) if re.fullmatch(r"[a-z0-9]+", t)]
        if terms:
            tight.append("(" + " AND ".join(f'"{t}"' for t in terms[:8]) + ")")
    broad_terms = [t for t in dict.fromkeys(t for q in plan.queries for t in q.terms) if re.fullmatch(r"[a-z0-9]+", t)]
    out: list[str] = []
    if tight:
        out.append("{title} : (" + " OR ".join(tight) + ")")
    if broad_terms and (len(broad_terms) > 1 or not tight):
        out.append("{title} : (" + " OR ".join(f'"{t}"' for t in broad_terms[:14]) + ")")
    return out


def fts_place_clause(plan: Plan) -> str | None:
    """
    A full-text clause on the posting's place for a search that names a city: the city and the places around it. None for a
    search with no city (nationwide, a state alone, remote). Used with the title query so a big saved copy returns the jobs
    near the person even when thousands of better-worded titles sit elsewhere.
    """
    loc = plan.loc
    if loc.nationwide or not loc.cities:
        return None
    names = list(loc.cities) + [c for c, _state in loc.near]
    parts: list[str] = []
    for name in names:
        words_ = re.findall(r"[a-z0-9]+", fold(name))
        if words_:
            parts.append("(" + " AND ".join(f'"{w}"' for w in words_) + ")")
    parts = list(dict.fromkeys(parts))
    return "{location} : (" + " OR ".join(parts[:16]) + ")" if parts else None


def fts_place_queries(plan: Plan) -> list[str]:
    """The title queries (tight to broad) each narrowed to the places asked for. Empty when the search names no city."""
    place = fts_place_clause(plan)
    if not place:
        return []
    return [f"({q}) AND {place}" for q in fts_queries(plan)]


def like_terms(plan: Plan) -> list[str]:
    out: list[str] = []
    for q in plan.queries:
        for t in q.terms:
            if t not in out:
                out.append(t)
    return out


# ---- scoring ----------------------------------------------------------------------------------------------------

def _contiguous(needle: list[str], hay: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


def title_fit(plan: Plan, title: str, typed_only: bool = False) -> float:
    """0 to 1: how well a posting's title matches the best of the titles asked for. `typed_only` ignores the alternative titles."""
    p_all = all_stems(title)
    p_content = content_stems(title)
    p_set = set(p_all)
    p_level = level_of(title)
    best = 0.0
    for q in plan.queries:
        if typed_only and q.weight < 1.0:
            continue
        have = [s for s in q.stems if s in p_set]
        coverage = len(have) / len(q.stems)
        need = 1.0 if len(q.stems) <= 2 else 0.66  # a long title may miss one word; a short one may not
        if coverage + 1e-9 < need:
            continue
        phrase = 1.0 if _contiguous(q.stems, p_content) else (0.6 if coverage == 1.0 else 0.0)
        precision = min(1.0, len(have) / max(len(p_content), 1))
        score = 0.5 * coverage + 0.3 * phrase + 0.2 * precision
        if q.weight >= 1.0 and coverage == 1.0 and phrase == 1.0:
            score = max(score, 0.96)  # the title typed, as written, inside the posting's title ("Project Coordinator, Market Access"): extra words do not count against it
        if len(q.stems) >= 3 and q.stems[-2] not in p_set:
            score *= 0.6  # the word that names the field ("cycle" in "revenue cycle manager") is missing: "Revenue Operations Manager" is not it
        if q.level is not None and p_level is not None:
            score -= min(0.4, 0.16 * abs(q.level - p_level)) if strict() else min(0.3, 0.12 * abs(q.level - p_level))
        elif p_level is not None and p_level <= 1 and (q.level is None or q.level > 1):
            score -= 0.2  # an assistant or intern role when none was asked for
        elif strict() and q.level is None and p_level is not None and p_level >= DIRECTOR_LEVEL:
            score -= 0.15  # a director, VP or chief when no level was asked for
        elif q.level is not None and p_level is None:
            score -= 0.03
        best = max(best, max(0.0, min(1.0, score)) * q.weight)
    return best


BORDERLINE_TITLE = 0.70  # a title fit below this is "partly matches": the description gets a say
DESC_MIN_CHARS = 300  # a description shorter than this says too little to count against a job
DESC_CONFIRM_BONUS = 0.15
DESC_DEMOTE = 0.6
DESC_READ_CHARS = 4000  # how much of a description is read when it confirms or demotes a partly matching title


def description_signal(plan: Plan, description: str | None) -> int:
    """
    +1 when the description is about the kind of work asked for (every word of it, such as "revenue" and "cycle"), -1 when
    there is a real description and it is not, 0 when there is none to judge (or nothing to judge it by).
    """
    if not plan.desc_phrases or not description or len(description) < DESC_MIN_CHARS:
        return 0
    have = set(all_stems(description[:DESC_READ_CHARS]))
    return 1 if any(all(d in have for d in domain) for domain, _head in plan.desc_phrases) else -1


def _recency(posted: dt.date | None, today: dt.date) -> float:
    if posted is None:
        return 0.4
    return math.exp(-max((today - posted).days, 0) / 45.0)


@dataclass
class Scored:
    row: dict[str, Any]
    fit: float
    title_fit: float
    place_fit: float
    via_description: bool = False  # the title alone did not match; the description opening did
    needs_description: bool = False  # the title only partly matches and no description is saved: reading it would settle the job


def score_row(plan: Plan, row: dict[str, Any], today: dt.date | None = None) -> Scored | None:
    """A candidate's overall fit, or None when it should not be shown at all (wrong title, place, work type, pay or date)."""
    today = today or dt.date.today()
    company = (row.get("company") or "").lower()
    if company and name_excluded(company, list(plan.excluded)):
        return None
    tf = title_fit(plan, row["title"])
    via_desc = False
    needs_text = False
    if MIN_TITLE_FIT <= tf < BORDERLINE_TITLE and plan.desc_phrases and title_fit(plan, row["title"], typed_only=True) >= tf - 1e-9:
        # A title that only partly matches what was typed ("Revenue Operations Manager" for "revenue cycle manager"): the
        # description settles it. About the work asked for lifts it; about something else sinks it; no description changes nothing.
        signal = description_signal(plan, row.get("description"))
        needs_text = signal == 0 and len(row.get("description") or "") < DESC_MIN_CHARS
        if signal > 0:
            tf = min(1.0, tf + DESC_CONFIRM_BONUS)
        elif signal < 0:
            tf *= DESC_DEMOTE
    elif strict() and tf >= BORDERLINE_TITLE and plan.desc_phrases and description_signal(plan, row.get("description")) < 0:
        tf *= DESC_OTHER_WORK  # the title matches but a real description is about something else
    if tf < MIN_TITLE_FIT:
        if desc_hit(plan, row.get("description"), set(all_stems(row["title"]))):
            tf, via_desc = DESC_TITLE_FLOOR, True  # "Business Analyst" whose description is about revenue cycle work
        else:
            return None
    posted_early = _date(row.get("posted_at") or row.get("seen_date"))
    if strict() and posted_early and (today - posted_early).days > HIDE_AFTER_DAYS:
        return None  # open more than 90 days: probably filled or forgotten
    wt = effective_work_type(row.get("work_type"), row.get("location"))  # on site unless the employer says remote or hybrid; unknown only when the place is
    if plan.work_type != "any" and wt is not None and wt != plan.work_type:
        return None  # a job whose place is unknown is kept; one that is something else is not
    if plan.work_type == "remote" and wt is None and not is_vague_place(row.get("location")):
        return None  # it names a city and never says remote, so it is not a remote job
    if plan.work_type == "remote":
        loc = LocationQuery(states=plan.loc.states, remote=True, empty=plan.loc.empty)
    else:
        loc = plan.loc
    lf = location_fit(loc, row.get("location"), wt)
    if lf <= 0.0:
        return None
    if is_vague_place(row.get("location")) and title_names_foreign(row["title"]):
        return None  # no place listed, but the title puts the job in another country: the launch market is the US
    if is_vague_place(row.get("location")) and title_names_other_state(plan, row["title"]):
        return None  # no place listed, but the title says where ("Marine Biologist - Alaska"): not the place asked for
    mid = row.get("pay_mid")
    if mid is None and row.get("pay_text"):
        mid = pay_midpoint(row["pay_text"])  # saved before the pay could be read: read it now
    if plan.pay_floor and mid is not None and mid < plan.pay_floor:
        return None
    posted = _date(row.get("posted_at") or row.get("seen_date"))
    if plan.window_days and (posted is None or (today - posted).days > plan.window_days):
        return None  # a date window was asked for: a posting that cannot show when it was posted does not qualify
    kw = 0.0
    if plan.keyword_phrases:
        # Keywords are required: every word of at least one keyword must be in the title, employer, place or (when the
        # posting's text was saved) its description. A posting that has none of them is left out.
        if not keyword_match(plan, f"{row['title']} {row.get('company') or ''} {row.get('location') or ''} {row.get('description') or ''}"):
            return None
        kw = 1.0
    fit = W_TITLE * tf + W_PLACE * lf + W_RECENT * _recency(posted, today) + W_PAY * (1.0 if mid is not None else 0.0) + W_KEYWORD * kw
    if posted and (today - posted).days > STALE_DAYS:
        fit *= STALE_FACTOR  # a posting open for half a year or more is often forgotten: it ranks below fresher ones
    if strict() and posted:
        age = (today - posted).days
        fit *= 0.88 if age > 60 else (0.95 if age > 30 else 1.0)  # fresher postings rank first
    if via_desc or desc_hit(plan, row.get("description")):
        fit += W_DESC
    if strict() and via_desc:
        fit = min(fit, DESC_ONLY_CAP)
    return Scored(row=row, fit=round(min(fit, 1.0), 4), title_fit=tf, place_fit=lf, via_description=via_desc, needs_description=needs_text)


def title_names_other_state(plan: Plan, title: str) -> bool:
    """True when a title spells out a US state (not the one asked for) and the search names a place, e.g. "Marine Biologist - Alaska" in a Honolulu search."""
    if plan.loc.empty or plan.loc.nationwide or not plan.loc.states:
        return False
    folded = f" {fold(title)} "
    named = {abbr for name, abbr in STATE_BY_NAME.items() if f" {name} " in folded}
    return bool(named) and not (named & plan.loc.states)


def place_ok(plan: Plan, location: str | None, work_type: str | None) -> bool:
    """False when a posting's place rules it out (another country, or somewhere other than the place asked for): the saved-list rule, for web results too."""
    if plan.work_type == "remote":
        loc = LocationQuery(states=plan.loc.states, remote=True, empty=plan.loc.empty)
    else:
        loc = plan.loc
    return location_fit(loc, location, work_type) > 0.0


def keyword_match(plan: Plan, text: str) -> bool:
    """True when no keywords were asked for, or the text holds every word of at least one of them."""
    if not plan.keyword_phrases:
        return True
    have = set(all_stems(text))
    return any(all(k in have for k in phrase) for phrase in plan.keyword_phrases)


def fit_for_item(plan: Plan, title: str, location: str | None, work_type: str | None, posted: dt.date | None) -> float:
    """A fit for a result found some other way (the web search), so every result is ordered by the same measure. Never excludes."""
    today = dt.date.today()
    tf = title_fit(plan, title)
    lf = location_fit(plan.loc, location, work_type)
    return round(W_TITLE * tf + W_PLACE * lf + W_RECENT * _recency(posted, today), 4)


def rank(plan: Plan, rows: list[dict[str, Any]], today: dt.date | None = None) -> list[Scored]:
    scored = [s for r in rows if (s := score_row(plan, r, today)) is not None]
    scored.sort(key=lambda s: s.row.get("posted_at") or s.row.get("seen_date") or "", reverse=True)  # newer first among equals
    scored.sort(key=lambda s: -s.fit)  # stable: best fit first
    return scored


PER_EMPLOYER_CAP = 4  # results one employer may take before others get a turn
PER_TITLE_CAP = 1  # the same title at the same employer (an opening repeated in many cities) counts once


def diversify(scored: list[Scored]) -> list[Scored]:
    """
    Keeps the best-first order but stops one employer from filling the screen: the same title at the same employer is shown
    once and an employer gets at most a few places; the rest follow after everyone else, so nothing is lost when there are
    few results. A search with plenty of good matches reads as a mix of employers instead of nine copies of one posting.
    """
    kept: list[Scored] = []
    later: list[Scored] = []
    per_employer: dict[str, int] = {}
    per_title: dict[tuple[str, str], int] = {}
    for s in scored:
        company = fold(s.row.get("company") or "")
        title_key = (company, " ".join(sorted(set(all_stems(s.row.get("title") or "")))))
        if per_employer.get(company, 0) >= PER_EMPLOYER_CAP or per_title.get(title_key, 0) >= PER_TITLE_CAP:
            later.append(s)
            continue
        per_employer[company] = per_employer.get(company, 0) + 1
        per_title[title_key] = per_title.get(title_key, 0) + 1
        kept.append(s)
    return kept + later


def _date(value: Any) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None
