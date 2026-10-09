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
    STOPWORDS,
    LocationQuery,
    all_stems,
    content_stems,
    fold,
    is_vague_place,
    level_of,
    location_fit,
    parse_location_query,
    split_titles,
    words,
)

MIN_TITLE_FIT = 0.35  # below this a title only shares a word or two with the search: left out
CANDIDATE_LIMIT = 600  # postings read from the index per search, however large the saved copy is
EXPANDED_WEIGHT = 0.92  # an alternative title counts for a little less than the one the person typed

W_TITLE, W_PLACE, W_RECENT, W_PAY, W_KEYWORD = 0.62, 0.22, 0.08, 0.04, 0.04


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
    pay_floor: int | None = None
    window_days: int = 0
    excluded: list[str] = field(default_factory=list)

    def earliest(self, today: dt.date | None = None) -> dt.date | None:
        return (today or dt.date.today()) - dt.timedelta(days=self.window_days) if self.window_days else None


def make_query(title: str, weight: float = 1.0) -> TitleQuery | None:
    stems = content_stems(title)
    if not stems:
        return None
    terms = [w for w in words(title) if w not in STOPWORDS and w not in SENIORITY_ONLY]
    return TitleQuery(raw=title, stems=stems, terms=terms, level=level_of(title), weight=weight)


def build_plan(criteria: Any, extra_titles: list[str] | None = None) -> Plan:
    """`criteria` is a JobSearchIn (read by attribute so tests can pass any object with the same fields)."""
    queries: list[TitleQuery] = []
    seen: set[str] = set()
    for title in split_titles(criteria.titles):
        q = make_query(title)
        if q and fold(title) not in seen:
            seen.add(fold(title))
            queries.append(q)
    for title in extra_titles or []:
        q = make_query(title, EXPANDED_WEIGHT)
        if q and fold(title) not in seen:
            seen.add(fold(title))
            queries.append(q)
    keywords = [s for s in content_stems(criteria.keywords) if s] if getattr(criteria, "keywords", None) else []
    floor = None
    if getattr(criteria, "target_salary", None):
        floor = int(criteria.target_salary * 0.95)  # same 5% slack the rest of Job Search uses
    excluded = [e.strip().lower() for e in re.split(r"[,;\n]", getattr(criteria, "exclude_companies", None) or "") if e.strip()][:20]
    return Plan(
        queries=queries,
        loc=parse_location_query(getattr(criteria, "location", None)),
        work_type=getattr(criteria, "work_type", "any") or "any",
        keywords=keywords,
        pay_floor=floor,
        window_days=int(getattr(criteria, "posted_within_days", 0) or 0),
        excluded=excluded,
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


def title_fit(plan: Plan, title: str) -> float:
    """0 to 1: how well a posting's title matches the best of the titles asked for."""
    p_all = all_stems(title)
    p_content = content_stems(title)
    p_set = set(p_all)
    p_level = level_of(title)
    best = 0.0
    for q in plan.queries:
        have = [s for s in q.stems if s in p_set]
        coverage = len(have) / len(q.stems)
        need = 1.0 if len(q.stems) <= 2 else 0.66  # a long title may miss one word; a short one may not
        if coverage + 1e-9 < need:
            continue
        phrase = 1.0 if _contiguous(q.stems, p_content) else (0.6 if coverage == 1.0 else 0.0)
        precision = min(1.0, len(have) / max(len(p_content), 1))
        score = 0.5 * coverage + 0.3 * phrase + 0.2 * precision
        if q.level is not None and p_level is not None:
            score -= min(0.3, 0.12 * abs(q.level - p_level))
        elif p_level is not None and p_level <= 1 and (q.level is None or q.level > 1):
            score -= 0.2  # an assistant or intern role when none was asked for
        elif q.level is not None and p_level is None:
            score -= 0.03
        best = max(best, max(0.0, min(1.0, score)) * q.weight)
    return best


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


def score_row(plan: Plan, row: dict[str, Any], today: dt.date | None = None) -> Scored | None:
    """A candidate's overall fit, or None when it should not be shown at all (wrong title, place, work type, pay or date)."""
    today = today or dt.date.today()
    company = (row.get("company") or "").lower()
    if any(e in company or company in e for e in plan.excluded if company):
        return None
    tf = title_fit(plan, row["title"])
    if tf < MIN_TITLE_FIT:
        return None
    wt = row.get("work_type")
    if plan.work_type != "any" and wt is not None and wt != plan.work_type:
        return None  # a posting that does not say how it works is kept; one that says something else is not
    if plan.work_type == "remote" and wt is None and not is_vague_place(row.get("location")):
        return None  # it names a city and never says remote, so it is not a remote job
    if plan.work_type == "remote":
        loc = LocationQuery(states=plan.loc.states, remote=True, empty=plan.loc.empty)
    else:
        loc = plan.loc
    lf = location_fit(loc, row.get("location"), wt)
    if lf <= 0.0:
        return None
    mid = row.get("pay_mid")
    if plan.pay_floor and mid is not None and mid < plan.pay_floor:
        return None
    posted = _date(row.get("posted_at"))
    if plan.window_days and posted and (today - posted).days > plan.window_days:
        return None
    kw = 0.0
    if plan.keywords:
        hay = set(all_stems(f"{row['title']} {row.get('company') or ''} {row.get('location') or ''}"))
        kw = 1.0 if any(k in hay for k in plan.keywords) else 0.0
    fit = W_TITLE * tf + W_PLACE * lf + W_RECENT * _recency(posted, today) + W_PAY * (1.0 if mid is not None else 0.0) + W_KEYWORD * kw
    return Scored(row=row, fit=round(fit, 4), title_fit=tf, place_fit=lf)


def fit_for_item(plan: Plan, title: str, location: str | None, work_type: str | None, posted: dt.date | None) -> float:
    """A fit for a result found some other way (the web search), so every result is ordered by the same measure. Never excludes."""
    today = dt.date.today()
    tf = title_fit(plan, title)
    lf = location_fit(plan.loc, location, work_type)
    return round(W_TITLE * tf + W_PLACE * lf + W_RECENT * _recency(posted, today), 4)


def rank(plan: Plan, rows: list[dict[str, Any]], today: dt.date | None = None) -> list[Scored]:
    scored = [s for r in rows if (s := score_row(plan, r, today)) is not None]
    scored.sort(key=lambda s: s.row.get("posted_at") or "", reverse=True)  # newer first among equals
    scored.sort(key=lambda s: -s.fit)  # stable: best fit first
    return scored


def _date(value: Any) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None
