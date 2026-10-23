"""
Ties the job cache together: searching it, keeping it up to date, and growing the employer list.

The list of employers grows from three places: the employers behind jobs you saved and results you were shown, links you
paste in the Employers panel, and employers the web search turns up. Reading them is a background job that is polite to
every site (see readers.py); searching the saved copy is instant and costs nothing.
"""

from __future__ import annotations

import asyncio
from itertools import zip_longest
import datetime as dt
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.services.jobcache import geo, matcher, onet
from app.services.jobcache.keys import loose_keys, url_key
from app.services.jobcache.readers import SYSTEMS, USER_AGENT, ReaderError, Throttle, employer_ref, make_client, read_employer
from app.services.jobcache.store import JobCache, guess_name, now_ts
from app.services.jobcache.text import effective_work_type, fold, is_vague_place, names_no_town, parse_location_query, place_ref

log = logging.getLogger("job_cache")

def timing_note(what: str, started: float) -> None:
    """One line saying how long a step of a search took, appended to data/search_timing.log (to see where the wait goes)."""
    try:
        from pathlib import Path

        path = Path(settings.JOB_CACHE_PATH).parent / "search_timing.log"
        if path.exists() and path.stat().st_size > 500_000:
            path.write_text("")
        with path.open("a") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {time.time() - started:6.1f}s  {what}\n")
    except Exception:  # timing notes must never get in the way of a search
        pass


SYSTEM_LABELS = {"workday": "Workday", "greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "smartrecruiters": "SmartRecruiters",
    "breezy": "Breezy HR", "workable": "Workable", "bamboohr": "BambooHR", "pinpoint": "Pinpoint", "jazzhr": "JazzHR", "jobvite": "Jobvite", "oracle": "Oracle Cloud", "icims": "iCIMS", "taleo": "Taleo", "phenom": "Phenom", "successfactors": "SuccessFactors", "dayforce": "Dayforce", "kpmg": "KPMG careers site", "deloitte": "Deloitte careers site", "talentbrew": "TalentBrew careers site", "jibe": "Jibe careers site",
}
CONCURRENT_EMPLOYERS = 4
PRIORITY_HOURS, REGULAR_HOURS = 6.0, 24.0


def disabled_systems() -> set[str]:
    return {s.strip().lower() for s in (settings.JOB_CACHE_DISABLED_SYSTEMS or "").split(",") if s.strip()}


# ---- searching --------------------------------------------------------------------------------------------------

@dataclass
class CacheOutcome:
    items: list[dict[str, Any]] = field(default_factory=list)
    unread: list[tuple[int, str]] = field(default_factory=list)  # (posting id, link) of partly matching jobs with no saved text
    matches: int = 0  # postings that fit and were not already shown or saved
    matches_capped: bool = False  # True when the search read its limit of candidates, so there may be more
    coverage: dict[str, Any] = field(default_factory=dict)


def to_item(scored: matcher.Scored) -> dict[str, Any]:
    r = scored.row
    posted = r.get("posted_at") or r.get("seen_date")  # the board's own date, else the day we first saw it (only saved when trustworthy)
    return {
        "title": r["title"],
        "company": r["company"],
        "location": r.get("location"),
        "work_type": effective_work_type(r.get("work_type"), r.get("location")),
        "salary_text": r.get("pay_text"),
        "posted_at": dt.date.fromisoformat(posted[:10]) if isinstance(posted, str) and len(posted) >= 10 else None,
        "summary": None,
        "_desc": (r.get("description") or "")[:3000] or None,  # working note for telling copies of one job apart; never saved
        "url": r["url"],
        "url_key": url_key(r["url"]),
        "grounded": True,  # the employer's own list: as direct as a link gets
        "fit": scored.fit,
        "employer_id": r["eid"],
        "read_at": r.get("read_ok"),  # when the employer's list was last read; lets the search skip a second check on a fresh list
    }


UNREAD_LOOK = 400  # how far down the ranking a partly matching job is worth reading
UNREAD_FETCH = 40  # postings read per search; each is saved, so a repeat search reads nothing new


_SR_SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def _description_request(url: str) -> tuple[str, str] | None:
    """(kind, address) for hiring systems that serve a posting's text as data; None when the posting page itself must be read."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    segs = [p for p in parts.path.split("/") if p]
    if host == "jobs.smartrecruiters.com" and len(segs) >= 2:
        posting_id = segs[1].split("-")[0]
        return "smartrecruiters", f"https://api.smartrecruiters.com/v1/companies/{segs[0]}/postings/{posting_id}"
    if host == "apply.workable.com" and len(segs) >= 3 and segs[1] == "j":
        return "workable", f"https://apply.workable.com/api/v2/accounts/{segs[0]}/jobs/{segs[2]}"
    if host.endswith(".bamboohr.com") and len(segs) >= 2 and segs[0] == "careers" and segs[1].isdigit():
        return "bamboohr", f"{parts.scheme}://{parts.netloc}/careers/{segs[1]}/detail"  # the page is built by script; the text is in this data
    if host.endswith(".icims.com") and "/jobs/" in parts.path:
        return "icims", f"{parts.scheme}://{parts.netloc}{parts.path}?in_iframe=1"
    return None


def _data_description(kind: str, data: Any) -> str | None:
    """The posting text inside a SmartRecruiters or Workable answer."""
    if not isinstance(data, dict):
        return None
    if kind == "smartrecruiters":
        sections = ((data.get("jobAd") or {}).get("sections") or {}) if isinstance(data.get("jobAd"), dict) else {}
        texts = [str((sections.get(k) or {}).get("text") or "") for k in _SR_SECTIONS if isinstance(sections.get(k), dict)]
        return " ".join(t for t in texts if t) or None
    if kind == "workable":
        texts = [str(data.get(k) or "") for k in ("description", "requirements", "benefits")]
        return " ".join(t for t in texts if t) or None
    if kind == "bamboohr":
        opening = ((data.get("result") or {}).get("jobOpening") or {}) if isinstance(data.get("result"), dict) else {}
        return str(opening.get("description") or "") or None
    return None


_ICIMS_CONTENT = re.compile(r'class="[^"]*iCIMS_JobContent[^"]*"[^>]*>(.*)', re.S | re.I)


async def _page_description(url: str, why: dict[str, int] | None = None) -> str | None:
    """
    The description a posting page publishes (structured job details for search engines; the page body for iCIMS), or None.
    `why` collects the reason when nothing could be read, so a hiring system that keeps failing can be understood.
    """
    from app.services.discovery import manual_extraction as mx
    from app.services.safe_fetch import safe_get

    def note(reason: str) -> None:
        if why is not None:
            why[reason] = why.get(reason, 0) + 1

    req = _description_request(url)
    address = req[1] if req and req[0] == "icims" else url
    try:
        resp = await safe_get(address, headers={"User-Agent": mx._USER_AGENT, "Accept": "text/html,application/json"}, timeout=8.0)
    except Exception as exc:
        note(f"error {type(exc).__name__}")
        return None
    if resp.status_code != 200:
        note(f"http {resp.status_code}")
        return None
    body = resp.text[:600000]
    for block in mx._JSONLD_PATTERN.findall(body):
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        for item in mx._flatten_jsonld(data):
            if mx._is_job_posting(item) and isinstance(item.get("description"), str) and item["description"].strip():
                return item["description"]
    if req and req[0] == "icims":
        m = _ICIMS_CONTENT.search(body)
        if m:
            return m.group(1)[:20000]
    note("page has no job details")
    return None


DESC_FILL_CHARS = 4000  # the portion of a description kept when filling in gradually: what search reads, and small to store
DESC_FILL_PER_EMPLOYER = 15  # postings read from one employer's site per refresh
NEW_EMPLOYER_PER_EMPLOYER = 30  # postings read from a newly added employer's site, in the batch that follows its first read
DESC_FILL_SYSTEMS_WITH_TEXT = {"greenhouse", "ashby", "lever", "jibe", "workable"}  # their lists already carry the text (Workable on each refresh)


async def read_missing_descriptions(unread: list[tuple[int, str]], max_chars: int | None = None, mark_failures: bool = False, why: dict[str, int] | None = None) -> int:
    """
    Most hiring systems' job lists carry no description, but each posting can be read on its own: Workday as data, the others
    from the structured job details every posting page publishes for search engines. The few that only partly match the search
    are read here and saved, so the description can decide whether they belong. Returns how many were saved.
    """
    import httpx

    from app.services.discovery.ats import workday_api_url
    from app.services.jobcache.readers import USER_AGENT
    from app.services.jobcache.text import html_to_text, pay_from_text

    if not unread:
        return 0
    cache = JobCache()
    gate = asyncio.Semaphore(8 if not mark_failures else 4)  # the gradual fill is slower and gentler than a search waiting on an answer
    saved = 0
    failed: list[int] = []

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}) as client:

        async def one(posting_id: int, url: str) -> None:
            nonlocal saved
            api = workday_api_url(url)
            try:
                async with gate:
                    req = _description_request(url)
                    if api:
                        resp = await client.get(api)
                        info = (resp.json() or {}).get("jobPostingInfo") or {} if resp.status_code == 200 else {}
                        markup = info.get("jobDescription")
                        if not markup and why is not None:
                            why[f"workday http {resp.status_code}"] = why.get(f"workday http {resp.status_code}", 0) + 1
                    elif req and req[0] in ("smartrecruiters", "workable", "bamboohr"):
                        resp = await client.get(req[1])
                        markup = _data_description(req[0], resp.json()) if resp.status_code == 200 else None
                        if not markup and why is not None:
                            key = f"{req[0]} http {resp.status_code}" if resp.status_code != 200 else f"{req[0]} answer has no text"
                            why[key] = why.get(key, 0) + 1
                    else:
                        markup = await _page_description(url, why)
                text_ = html_to_text(markup)
                if text_ and await asyncio.to_thread(cache.set_description, posting_id, text_, max_chars):
                    saved += 1
                    pay_text, pay_mid = pay_from_text(text_)  # read from the whole text, even where only the start of it is kept
                    if pay_text and pay_mid:
                        await asyncio.to_thread(cache.set_pay, posting_id, pay_text, pay_mid)
                else:
                    failed.append(posting_id)
            except Exception:  # one posting that cannot be read is simply left as it was
                failed.append(posting_id)

        await asyncio.gather(*(one(i, u) for i, u in unread))
    if mark_failures and failed:
        await asyncio.to_thread(cache.mark_description_unavailable, failed)
    return saved


async def fill_places(cache: JobCache, limit: int = 150, per_employer: int = 10, only_systems: list[str] | None = None) -> tuple[int, int]:
    """
    Opens postings whose list says only "3 Locations" and saves where they really are, so a search for a city finds them without
    waiting. A few from each employer per batch. Returns (tried, places saved).
    """
    from app.services.discovery import web_search

    todo = await asyncio.to_thread(cache.vague_place_postings, limit, per_employer, only_systems)
    if not todo:
        return 0, 0
    icims = [i for i in todo if (urlsplit(i["url"]).hostname or "").endswith(".icims.com")]
    todo = [i for i in todo if i not in icims]
    saved = await _icims_places(cache, icims)
    before = {id(i): i["location"] for i in todo}
    await web_search.enrich_from_ats(todo)
    unresolved: list[str] = []
    for item in todo:
        loc = item.get("location")
        if loc and loc != before[id(item)] and not is_vague_place(loc) and not names_no_town(loc):
            if await asyncio.to_thread(cache.set_location, item["url"], loc):
                saved += 1
                continue
        host = urlsplit(item["url"]).hostname or ""
        asked_system = host.endswith(("myworkdayjobs.com", "greenhouse.io", "ashbyhq.com", "lever.co"))
        if item.get("ats_checked") or not asked_system:  # the employer's system answered with no better place, or cannot be asked: do not open it again
            unresolved.append(item["url"])
    await asyncio.to_thread(cache.mark_place_tried, unresolved)
    return len(todo) + len(icims), saved


async def _icims_places(cache: JobCache, items: list[dict[str, Any]]) -> int:
    """iCIMS job lists often show no place; the job page publishes it. Saves what the pages say and marks the pages that say none."""
    from app.services.discovery import manual_extraction as mx
    from app.services.jobcache.text import place_from_page
    from app.services.safe_fetch import safe_get

    if not items:
        return 0
    host_gates: dict[str, asyncio.Semaphore] = {}
    gate = asyncio.Semaphore(8)  # these pages are on many different employers' sites, so reading more at once is not hard on any one of them
    saved = 0
    none: list[str] = []

    async def one(item: dict[str, Any]) -> None:
        nonlocal saved
        req = _description_request(item["url"])
        address = req[1] if req and req[0] == "icims" else item["url"]
        host = urlsplit(item["url"]).hostname or ""
        async with host_gates.setdefault(host, asyncio.Semaphore(2)), gate:  # never more than two at once on one employer's site
            try:
                resp = await safe_get(address, headers={"User-Agent": mx._USER_AGENT, "Accept": "text/html"}, timeout=10.0)
            except Exception:
                return
            await asyncio.sleep(0.5)
        if resp.status_code in (404, 410):
            none.append(item["url"])
            return
        if resp.status_code != 200:
            return
        place = place_from_page(resp.text[:800000])
        if place and not is_vague_place(place) and await asyncio.to_thread(cache.set_location, item["url"], place):
            saved += 1
        else:
            none.append(item["url"])

    by_host: dict[str, list[dict[str, Any]]] = {}
    for i in items:
        by_host.setdefault(urlsplit(i["url"]).hostname or "", []).append(i)
    spread = [x for group in zip_longest(*by_host.values()) for x in group if x]
    await asyncio.gather(*(one(i) for i in spread))
    await asyncio.to_thread(cache.mark_place_tried, none)
    return saved


DATE_GAP_SYSTEMS = ["icims", "bamboohr", "talentbrew", "jobvite", "taleo", "deloitte", "kpmg", "successfactors", "pinpoint"]  # their lists carry no posted date; the job page does


async def _page_posted_date(url: str) -> tuple[str, Any]:
    """("date", day) when the job page shows one, ("none", None) when the page was read and shows none, ("error", None) when it could not be read."""
    from app.services.discovery import manual_extraction as mx
    from app.services.jobcache.text import posted_from_page
    from app.services.safe_fetch import safe_get

    req = _description_request(url)
    address = req[1] if req and req[0] in ("icims", "bamboohr") else url  # iCIMS shows its details on the ?in_iframe=1 page; BambooHR in its detail data
    try:
        resp = await safe_get(address, headers={"User-Agent": mx._USER_AGENT, "Accept": "text/html,application/json"}, timeout=10.0)
    except Exception:
        return "error", None
    if resp.status_code in (404, 410):
        return "none", None
    if resp.status_code != 200:
        return "error", None
    day = posted_from_page(resp.text[:800000])
    return ("date", day) if day else ("none", None)


async def fill_dates(cache: JobCache, limit: int = 150, per_employer: int = 10) -> tuple[int, int]:
    """
    Opens postings whose list shows no posted date (iCIMS, BambooHR, TalentBrew, Jobvite, Taleo, Deloitte, KPMG, SuccessFactors,
    Pinpoint) and saves the date their page publishes. A few from each employer per batch, gently. A page that shows no date is
    marked so it is not opened again; a page that could not be read is tried again later. Returns (tried, dates saved).
    """
    todo = await asyncio.to_thread(cache.undated_postings, DATE_GAP_SYSTEMS, limit, per_employer)
    if not todo:
        return 0, 0
    gate = asyncio.Semaphore(4)
    saved = 0
    none: list[int] = []

    async def one(posting_id: int, url: str) -> None:
        nonlocal saved
        async with gate:
            kind, day = await _page_posted_date(url)
        if kind == "date" and await asyncio.to_thread(cache.set_posted_at, posting_id, day):
            saved += 1
        elif kind == "none":
            none.append(posting_id)

    await asyncio.gather(*(one(i, u) for i, u in todo))
    await asyncio.to_thread(cache.mark_date_tried, none)
    return len(todo), saved


async def fill_descriptions_gradually(cache: JobCache, employer_ids: list[int] | None = None, per_employer: int | None = None, budget: int | None = None) -> int:
    """
    After each refresh, reads a small batch of postings that have no saved description and keeps the first part of each. Over
    many refreshes the saved lists gain descriptions without any one employer's site being read hard. Returns how many were saved.
    """
    budget = settings.JOB_CACHE_DESCRIPTION_FILL if budget is None else budget
    if budget <= 0 or (employer_ids is not None and not employer_ids):
        return 0
    todo = await asyncio.to_thread(
        cache.postings_without_description, budget, per_employer or DESC_FILL_PER_EMPLOYER, DESC_FILL_SYSTEMS_WITH_TEXT, employer_ids
    )
    return await read_missing_descriptions(todo, max_chars=DESC_FILL_CHARS, mark_failures=True)


def search_sync(criteria: Any, known_keys: set[str], extra_titles: list[str] | None, pool: int, extra_places: list[str] | None = None) -> CacheOutcome:
    cache = JobCache()
    coverage = cache.counts()
    plan = matcher.build_plan(criteria, extra_titles, extra_places)
    if coverage["postings"] == 0 or not plan.queries:
        return CacheOutcome(coverage=coverage)
    off = disabled_systems()
    rows: list[dict[str, Any]] = []
    for query in matcher.fts_queries(plan) or [None]:
        rows = cache.candidates(query, matcher.like_terms(plan), matcher.CANDIDATE_LIMIT, plan.earliest())
        if len(rows) >= matcher.ENOUGH_TIGHT:
            break
    capped = len(rows) >= matcher.CANDIDATE_LIMIT
    # A big saved copy holds thousands of well-worded titles in other cities, so the best title matches alone can leave out
    # every job near the person. A search that names a city also pulls the best title matches within that city and its neighbors.
    have = {r["id"] for r in rows}
    for query in matcher.fts_place_queries(plan):
        near = cache.candidates(query, matcher.like_terms(plan), matcher.CANDIDATE_LIMIT, plan.earliest())
        rows += [r for r in near if r["id"] not in have]
        have.update(r["id"] for r in near)
        if len(near) >= matcher.ENOUGH_TIGHT:
            break
    desc_query = matcher.fts_desc_query(plan)
    if desc_query and cache.desc_ready():
        # postings whose title is a different one but whose description opening names this kind of work
        rows += cache.candidates_by_description(desc_query, matcher.DESC_CANDIDATE_LIMIT, plan.earliest(), {r["id"] for r in rows})
    rows = [r for r in rows if r["ats"] not in off]
    scored = matcher.diversify(matcher.rank(plan, rows))
    fresh = [s for s in scored if not (loose_keys(s.row["url"]) & known_keys)]
    unread = [(s.row["id"], s.row["url"]) for s in fresh[:UNREAD_LOOK] if s.needs_description][:UNREAD_FETCH]
    return CacheOutcome(
        unread=unread,
        items=[to_item(s) for s in fresh[:pool]],
        matches=len(fresh),
        matches_capped=capped,
        coverage=coverage,
    )


# The ranked matches of a recent search, kept for ten minutes so moving between pages of one search costs almost nothing.
_RANKED: dict[str, tuple[float, list[dict[str, Any]]]] = {}
RANKED_TTL_SECONDS = 600
RANKED_KEEP = 6


def _ranked_key(criteria: Any) -> str:
    fields = [getattr(criteria, k, None) for k in ("titles", "location", "work_type", "keywords", "exclude_companies", "target_salary", "require_salary", "posted_within_days", "include_remote")]
    return json.dumps(fields, default=str)


# A web search that just ran for exactly these criteria is not repeated within the hour: the employers it found are in the saved lists.
_WEB_DONE: dict[str, float] = {}
WEB_REPEAT_SECONDS = 3600


def _web_key(criteria: Any) -> str:
    def norm(v: Any) -> Any:
        return re.sub(r"\s+", " ", v.strip().lower()) if isinstance(v, str) else v

    fields = [norm(getattr(criteria, k, None)) for k in ("titles", "location", "work_type", "keywords", "exclude_companies", "target_salary", "require_salary", "posted_within_days", "include_remote")]
    return json.dumps(fields, default=str)


def web_searched_recently(criteria: Any) -> bool:
    done = _WEB_DONE.get(_web_key(criteria))
    return done is not None and time.time() - done < WEB_REPEAT_SECONDS


def note_web_searched(criteria: Any) -> None:
    now = time.time()
    _WEB_DONE[_web_key(criteria)] = now
    for old in [k for k, t in _WEB_DONE.items() if now - t >= WEB_REPEAT_SECONDS]:
        _WEB_DONE.pop(old, None)


def collapse_listings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    One result for a job listed several times: the same employer, title (ignoring a requisition code), place, pay and posting
    date AND the same opening words of the description. The best-ranked copy stays. Two real openings that merely share a title
    differ in at least one of these, so they stay two results.
    """
    from app.services.jobcache.text import _squash, title_without_code

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        desc = _squash((item.get("_desc") or "")[:300])
        if not desc and item.get("salary_text") and title_without_code(item.get("title")) != (item.get("title") or ""):
            desc = "nodescription"  # no description saved: a title that carries a requisition code and the same pay and date is evidence enough
        if item.get("location") and item.get("posted_at") and desc:
            key = "|".join((_squash(item.get("company")), _squash(title_without_code(item.get("title"))), _squash(item["location"]),
                            _squash(item.get("salary_text")), str(item["posted_at"]), desc))
            if key in seen:
                continue
            seen.add(key)
        out.append(item)
    return out


DESC_READ_SECONDS = 20.0  # the most a search waits while reading the descriptions of partly matching jobs


async def ranked_items(criteria: Any) -> list[dict[str, Any]]:
    """Every match in the saved lists for this search, best first. The same list is reused for ten minutes."""
    key = _ranked_key(criteria)
    now = time.time()
    hit = _RANKED.get(key)
    if hit and now - hit[0] < RANKED_TTL_SECONDS:
        return hit[1]
    cache = JobCache()
    counts = await asyncio.to_thread(cache.counts)
    if counts["postings"] == 0:
        return []
    t0 = time.time()
    extra, places = await asyncio.gather(expand_titles(criteria.titles), expand_places(getattr(criteria, "location", None)))
    timing_note(f"expand titles/places for {criteria.titles!r} {getattr(criteria, 'location', None)!r}", t0)
    out = await asyncio.to_thread(search_sync, criteria, set(), extra, 1_000_000, places)
    timing_note(f"saved-list search ({len(out.items)} items, {len(out.unread)} unread)", t0)
    if out.unread:
        saved = 0
        try:
            saved = await asyncio.wait_for(read_missing_descriptions(out.unread), timeout=DESC_READ_SECONDS)
        except asyncio.TimeoutError:
            # Each description is saved as soon as it is read, so the ones finished in time still count now, and the rest are picked up next time.
            log.warning("job search: reading descriptions took over %.0fs; continuing with what was read", DESC_READ_SECONDS)
            saved = 1
        except Exception:
            log.exception("job search: could not read the descriptions of partly matching jobs")
        if saved:  # the text now saved may settle those jobs: rank again
            out = await asyncio.to_thread(search_sync, criteria, set(), extra, 1_000_000, places)
    items = collapse_listings(out.items)
    timing_note("descriptions read, listings collapsed", t0)
    items = await resolve_vague_places(criteria, items, extra, places)
    timing_note(f"vague places resolved ({len(items)} left)", t0)
    for item in items:  # the description note only tells copies of one job apart: its opening is enough, and keeps the kept lists small
        if item.get("_desc"):
            item["_desc"] = item["_desc"][:600]
    _RANKED[key] = (now, items)
    for old in sorted(_RANKED, key=lambda k: _RANKED[k][0])[: max(len(_RANKED) - RANKED_KEEP, 0)]:
        _RANKED.pop(old, None)
    return items


RESOLVE_PLACES_MAX = 60  # multi-location jobs opened per new search: the best-ranked first
RESOLVE_PLACES_SECONDS = 12.0


async def resolve_vague_places(criteria: Any, items: list[dict[str, Any]], extra_titles: list[str] | None, extra_places: list[str] | None) -> list[dict[str, Any]]:
    """
    A job whose list says only "3 Locations" is opened (the best-ranked ones, with a time limit) to learn where it really is. The real
    places are saved, so it happens once per job. A job that turns out to be somewhere else leaves the list, so the match count is true.
    """
    from app.services.discovery import web_search

    plan = matcher.build_plan(criteria, extra_titles, extra_places)
    if plan.work_type == "remote" or plan.loc.empty or plan.loc.nationwide or not (plan.loc.cities or plan.loc.states):
        return items
    # a city search: a job that gives only a state ("PA") says nothing about the town either, so it is opened too
    unplaced = (lambda loc: is_vague_place(loc) or names_no_town(loc)) if plan.loc.cities else is_vague_place
    vague = [i for i in items if unplaced(i.get("location"))]
    vague.sort(key=lambda i: -(i.get("fit") or 0.0))
    todo = vague[:RESOLVE_PLACES_MAX]
    if not todo:
        return items
    before = {id(i): i.get("location") for i in todo}
    try:
        await asyncio.wait_for(web_search.enrich_from_ats(todo), timeout=RESOLVE_PLACES_SECONDS)
    except Exception:  # a slow or unreachable hiring system: those jobs stay as they were and are checked when their page opens
        log.warning("job search: could not open every multi-location job in time")
    cache = JobCache()
    gone: set[int] = set()
    for item in todo:
        if item.get("ats_live") is False:
            gone.add(id(item))
            continue
        loc = item.get("location")
        if loc and loc != before[id(item)] and not unplaced(loc):
            await asyncio.to_thread(cache.set_location, item["url"], loc)
            if not matcher.place_ok(plan, loc, item.get("work_type")):
                gone.add(id(item))
    for item in todo:  # the opened pages told their dates and pay too: the next steps need not ask again
        item.pop("ats_checked", None)
        item.pop("ats_live", None)
    # A job that still names no place was not opened (beyond the best 60, or its system did not answer): a search for a place does not
    # show it. Each search saves the places of the next 60, so over searches the list fills in.
    return [i for i in items if id(i) not in gone and not (unplaced(i.get("location")) and i.get("work_type") != "remote")]


async def drop_from_ranked(criteria: Any, urls: set[str]) -> None:
    """Takes jobs that failed a check when their page was opened (no pay, too old) off this search's list, so the count and later pages are right."""
    hit = _RANKED.get(_ranked_key(criteria))
    if not hit or not urls:
        return
    _RANKED[_ranked_key(criteria)] = (hit[0], [i for i in hit[1] if i["url"] not in urls])


async def add_to_ranked(criteria: Any, new_items: list[dict[str, Any]]) -> tuple[int, int]:
    """
    Slips jobs the web search found into this search's ranked list, at the place their match earns, so they appear on whichever
    page they belong to. Jobs already in the list (the same posting) are skipped. Returns (how many were added, the new total).
    """
    ranked = await ranked_items(criteria)
    have: set[str] = set()
    for item in ranked:
        have |= loose_keys(item["url"])
    fresh = []
    for item in new_items:
        keys = loose_keys(item["url"])
        if keys & have:
            continue
        have |= keys
        item = dict(item)
        item["fit"] = item.get("fit_score") if item.get("fit_score") is not None else item.get("fit", 0.0)
        fresh.append(item)
    if fresh:
        merged = sorted([*ranked, *fresh], key=lambda i: -(i.get("fit") or 0.0))  # stable: equal fits keep the saved list's order
        _RANKED[_ranked_key(criteria)] = (time.time(), collapse_listings(merged))
    return len(fresh), len(_RANKED[_ranked_key(criteria)][1]) if fresh else len(ranked)


async def expand_titles(titles: str) -> list[str]:
    """
    A few other titles employers use for the same kind of work, so a search for "revenue cycle manager" also finds
    "manager, patient financial services". One small AI call per new search wording, remembered afterwards; nothing from
    your profile is sent, only the words you typed. Returns [] if the AI is not set up or the answer is unusable.
    """
    known = onet.alternates(titles)  # the government's list of other names for the same job: free and the same every time
    if len(known) >= 4:
        return known
    return _merge_titles(known, await _expand_titles_ai(titles), titles)


def _merge_titles(known: list[str], more: list[str], titles: str) -> list[str]:
    given = {fold(t) for t in titles.split(",")}
    out: list[str] = []
    for t in [*known, *more]:
        if fold(t) not in given and fold(t) not in {fold(o) for o in out}:
            out.append(t)
    return out[:8]


async def _expand_titles_ai(titles: str) -> list[str]:
    model = settings.JOB_SEARCH_MODEL or settings.PRIMARY_FAST_MODEL
    if not model:
        return []
    cache = JobCache()
    key = "expand:" + fold(titles)
    saved = cache.meta_get(key)
    if saved is not None:
        try:
            return [t for t in json.loads(saved) if isinstance(t, str)]
        except ValueError:
            return []
    try:
        from app.services.llm.client import LLMClient

        result = await LLMClient().chat_completion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You list alternative job titles. Reply with ONLY a JSON array of up to 8 strings: other titles employers "
                        "commonly use for the same kind of work at the same seniority as the title given. Same field, same level. "
                        "No explanations, no duplicates of the given title."
                    ),
                },
                {"role": "user", "content": titles},
            ],
            temperature=0.0,
            max_tokens=300,
            timeout=40.0,
        )
        text = result.content
        start, end = text.find("["), text.rfind("]")
        data = json.loads(text[start : end + 1]) if start != -1 and end > start else []
    except Exception:  # the AI is optional here: no answer just means fewer alternative titles
        return []
    given = {fold(t) for t in titles.split(",")}
    out: list[str] = []
    for t in data if isinstance(data, list) else []:
        if isinstance(t, str) and 3 <= len(t) <= 80 and len(t.split()) <= 8 and fold(t) not in given and fold(t) not in {fold(o) for o in out}:
            out.append(t.strip())
    cache.meta_set(key, json.dumps(out[:8]))
    return out[:8]


async def expand_places(location: str | None) -> list[str]:
    """
    The cities around a place ("Boston, MA" -> Cambridge, Somerville, Quincy ...), so a search for Boston also finds jobs in
    greater Boston, including across a state line (Washington, DC and Arlington, VA). One small AI call per new place,
    remembered afterwards; only the place you typed is sent. Returns [] when the AI is not set up or the answer is unusable.
    """
    if not location or not location.strip():
        return []
    query = parse_location_query(location)
    if not query.cities:
        return []
    state = next(iter(query.states)) if len(query.states) == 1 else None
    around = geo.nearby(query.cities[0], state)  # known coordinates: places within 25 miles, worked out in code (free, instant, the same every time)
    if around:
        return around
    model = settings.JOB_SEARCH_MODEL or settings.PRIMARY_FAST_MODEL
    if not model:
        return []
    cache = JobCache()
    key = "near:" + fold(location)
    saved = cache.meta_get(key)
    if saved is not None:
        try:
            return [p for p in json.loads(saved) if isinstance(p, str)]
        except ValueError:
            return []
    try:
        from app.services.llm.client import LLMClient

        result = await LLMClient().chat_completion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You list the cities and towns that make up the greater metro area around a place, within about 25 miles "
                        "or a normal commute, where people who work in that place also live and work. Reply with ONLY a JSON array of up to "
                        "15 strings, each written as City, ST (US state abbreviation), nearest and largest first. Do not repeat the place given. "
                        "No explanations."
                    ),
                },
                {"role": "user", "content": location.strip()[:120]},
            ],
            temperature=0.0,
            max_tokens=300,
            timeout=40.0,
        )
        text_ = result.content
        start, end = text_.find("["), text_.rfind("]")
        data = json.loads(text_[start : end + 1]) if start != -1 and end > start else []
    except Exception:  # optional: no answer just means the search stays on the place typed
        return []
    out: list[str] = []
    for p in data if isinstance(data, list) else []:
        if isinstance(p, str) and 3 <= len(p) <= 60 and place_ref(p) and p.strip() not in out:
            out.append(p.strip())
    cache.meta_set(key, json.dumps(out[:15]))
    return out[:15]


async def search_cache(criteria: Any, known_keys: set[str], pool: int) -> CacheOutcome:
    """Searches the saved employer lists. Fast whatever their size; the only AI use is the one optional title lookup."""
    cache = JobCache()
    counts = await asyncio.to_thread(cache.counts)
    if counts["postings"] == 0:
        return CacheOutcome(coverage=counts)
    extra, places = await asyncio.gather(expand_titles(criteria.titles), expand_places(getattr(criteria, "location", None)))
    return await asyncio.to_thread(search_sync, criteria, known_keys, extra, pool, places)


def record_hits(employer_ids: list[int]) -> None:
    try:
        JobCache().employer_hits(employer_ids)
    except Exception:  # bookkeeping only
        log.exception("job cache: could not record which employers produced results")


# ---- growing the employer list -----------------------------------------------------------------------------------

def learn_from_links(pairs: list[tuple[str, str | None]], source: str) -> int:
    """Adds the employer behind each (link, company name) pair that is on one of the four hiring systems. Returns how many were new."""
    cache = JobCache()
    off = disabled_systems()
    added = 0
    seen: set[tuple[str, str]] = set()
    for url, company in pairs:
        ref = employer_ref(url) if url else None
        if not ref or ref in seen or ref[0] in off:
            continue
        seen.add(ref)
        _, created = cache.upsert_employer(ref[0], ref[1], company or "", source)
        added += 1 if created else 0
    return added


def seed_from_app(db: Any) -> int:
    """Employers behind the jobs you saved and the search results you were shown (a Session on the main database)."""
    from app.models.job_search import JobSearchResult
    from app.models.jobs import Job

    added = learn_from_links([(u, c) for u, c in db.query(Job.canonical_application_url, Job.company).all()], "saved_job")
    added += learn_from_links([(u, c) for u, c in db.query(JobSearchResult.url, JobSearchResult.company).all()], "search")
    return added


WEB_NEW_EMPLOYERS_MAX = 10  # employers adopted from one web search
_ADOPTING: set[asyncio.Task] = set()  # background reads in progress (kept so they are not dropped half way)


async def real_name_from_posting(guess: str, url: str) -> str | None:
    """The employer's name as one of its job pages states it, kept only when it is plainly the same employer as the guess."""
    from app.services.jobcache.text import company_from_page, same_company

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        found = company_from_page(resp.text[:500_000])
    except Exception:
        return None
    return found if found and same_company(guess, found) else None


async def adopt_employers_from_web(pairs: list[tuple[str, str | None]]) -> int:
    """
    Employers behind the jobs a web search found that the saved lists did not have yet: each one's own job list is read, and it is
    kept only when that list has open jobs (so a wrong or dead link adds nothing). Their jobs are then in every later search. The
    read runs in the background; returns how many employers will be tried.
    """
    cache = JobCache()
    off = disabled_systems()
    todo: list[tuple[str, str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for url, company in pairs:
        ref = employer_ref(url) if url else None
        if not ref or ref in seen or ref[0] in off:
            continue
        seen.add(ref)
        todo.append((ref[0], ref[1], company))
    fresh = []
    for system, identifier, company in todo:
        exists = await asyncio.to_thread(cache.find_employer, system, identifier)
        if not exists:
            fresh.append((system, identifier, company))
        if len(fresh) >= WEB_NEW_EMPLOYERS_MAX:
            break
    if not fresh:
        return 0

    async def read_all() -> None:
        new_ids: list[int] = []
        async with make_client() as client:
            throttle = Throttle()
            for system, identifier, company in fresh:
                eid, created = await asyncio.to_thread(cache.upsert_employer, system, identifier, company or "", "web_search")
                if not created:
                    continue
                try:
                    result = await read_employer(system, identifier, client, throttle)
                except Exception:  # a list we cannot read: the employer is not kept
                    await asyncio.to_thread(cache.delete_employer, eid)
                    continue
                if not result.postings:
                    await asyncio.to_thread(cache.delete_employer, eid)
                    continue
                if result.name:
                    await asyncio.to_thread(cache.upsert_employer, system, identifier, result.name, "web_search")
                elif " " not in (company or "") and result.postings:
                    # The list does not name its employer and the name we have is only the address run together ("Morganlewis"):
                    # a job page states the real one.
                    page_name = await real_name_from_posting(guess_name(system, identifier), result.postings[0].url)
                    if page_name:
                        await asyncio.to_thread(cache.rename_employer, eid, page_name)
                await asyncio.to_thread(cache.apply_refresh, eid, result.postings, now_ts(), PRIORITY_HOURS, result.complete)
                new_ids.append(eid)
        if new_ids and settings.JOB_CACHE_DESCRIPTION_FILL > 0:
            try:
                await fill_descriptions_gradually(cache, new_ids, NEW_EMPLOYER_PER_EMPLOYER, NEW_EMPLOYER_PER_EMPLOYER * len(new_ids))
                await fill_places(cache, 150, 10)
            except Exception:
                log.exception("job cache: could not fill in details for employers found by the web search")
        log.warning("job cache: web search added %d employers", len(new_ids))

    task = asyncio.create_task(read_all())
    _ADOPTING.add(task)
    task.add_done_callback(_ADOPTING.discard)
    return len(fresh)


class AddEmployerError(Exception):
    """The employer could not be added; the message is safe to show."""


async def add_employer(url: str, company: str | None = None) -> dict[str, Any]:
    ref = employer_ref(url)
    if ref is None:
        raise AddEmployerError("That link isn't from a hiring system we can read yet (Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Breezy, Workable, BambooHR, Pinpoint, JazzHR, Jobvite, Oracle Cloud, iCIMS, Taleo, Phenom, SuccessFactors, Dayforce, or the KPMG or Deloitte careers site). Paste a link to one of its job postings or its job list.")
    system, identifier = ref
    if system in disabled_systems():
        raise AddEmployerError(f"Reading {SYSTEM_LABELS[system]} is switched off.")
    cache = JobCache()
    eid, created = await asyncio.to_thread(cache.upsert_employer, system, identifier, company or "", "user_link")
    async with make_client() as client:
        try:
            result = await read_employer(system, identifier, client, Throttle())
        except ReaderError as exc:
            if created:
                await asyncio.to_thread(cache.delete_employer, eid)
            raise AddEmployerError(f"We couldn't read that employer's job list: {exc}.") from exc
    if result.name:
        await asyncio.to_thread(cache.upsert_employer, system, identifier, result.name, "user_link")
    await asyncio.to_thread(cache.apply_refresh, eid, result.postings, now_ts(), PRIORITY_HOURS, result.complete)
    with cache.session() as conn:
        conn.execute("UPDATE employers SET source = 'user_link' WHERE id = ? AND source = 'search'", (eid,))
    employer = cache.get_employer(eid)
    assert employer is not None
    return employer


# ---- keeping the copy up to date ---------------------------------------------------------------------------------

@dataclass
class RefreshState:
    running: bool = False
    total: int = 0
    done: int = 0
    started: float = 0.0
    finished: float | None = None
    summary: str = ""


STATE = RefreshState()
_LOCK = threading.Lock()


def refresh_state() -> dict[str, Any]:
    return {
        "running": STATE.running,
        "total": STATE.total,
        "done": STATE.done,
        "finished_at": dt.datetime.fromtimestamp(STATE.finished, tz=dt.timezone.utc).isoformat() if STATE.finished else None,
        "summary": STATE.summary,
    }


async def _refresh_async(only_ids: list[int] | None, limit: int, max_seconds: float) -> str:
    cache = JobCache()
    now = now_ts()
    due = cache.due_employers(now, limit, only_ids, disabled_systems())
    STATE.total, STATE.done = len(due), 0
    if not due:
        return "nothing was due"
    deadline = time.monotonic() + max_seconds
    sem = asyncio.Semaphore(CONCURRENT_EMPLOYERS)
    throttle = Throttle()
    tallies = {"ok": 0, "failed": 0, "new": 0, "closed": 0, "skipped": 0}
    first_reads: list[int] = []  # employers read for the first time: their descriptions are pulled in with them

    async with make_client() as client:

        async def one(emp: dict[str, Any]) -> None:
            async with sem:
                if time.monotonic() > deadline:
                    tallies["skipped"] += 1
                    STATE.done += 1
                    return
                label = f"{emp['name']} ({emp['ats']})"
                try:
                    result = await read_employer(emp["ats"], emp["identifier"], client, throttle)
                    if result.name:
                        cache.upsert_employer(emp["ats"], emp["identifier"], result.name, emp["source"])
                    priority = emp["source"] in ("saved_job", "user_link") or emp["hits"] > 0
                    done = cache.apply_refresh(emp["id"], result.postings, now_ts(), PRIORITY_HOURS if priority else REGULAR_HOURS, result.complete)
                    tallies["ok"] += 1
                    if done.new and done.new >= done.total:
                        first_reads.append(emp["id"])
                    tallies["new"] += done.new
                    tallies["closed"] += done.closed
                    log.warning(
                        "job cache: read %s: %d open, %d new, %d closed%s", label, done.total, done.new, done.closed,
                        f" ({'; '.join(result.notes)})" if result.notes else "",
                    )
                except ReaderError as exc:
                    cache.record_failure(emp["id"], str(exc), now_ts(), exc.retry_after)
                    tallies["failed"] += 1
                    log.warning("job cache: could not read %s: %s", label, exc)
                except Exception as exc:  # one employer must never stop the rest
                    cache.record_failure(emp["id"], f"{type(exc).__name__}: {exc}", now_ts())
                    tallies["failed"] += 1
                    log.exception("job cache: unexpected error reading %s", label)
                finally:
                    STATE.done += 1

        await asyncio.gather(*(one(e) for e in due))
    try:
        filled = 0
        if first_reads and settings.JOB_CACHE_DESCRIPTION_FILL > 0:  # a newly found employer gets a bigger first batch, so it is searchable by meaning from the start
            filled += await fill_descriptions_gradually(cache, first_reads, NEW_EMPLOYER_PER_EMPLOYER, NEW_EMPLOYER_PER_EMPLOYER * len(first_reads))
        filled += await fill_descriptions_gradually(cache)
    except Exception:
        log.exception("job cache: could not fill in descriptions")
        filled = 0
    try:  # multi-location postings (also from newly added employers) get their real places saved a few at a time, so city searches are quick
        if settings.JOB_CACHE_PLACE_FILL > 0:
            await fill_places(cache, settings.JOB_CACHE_PLACE_FILL, 10)
    except Exception:
        log.exception("job cache: could not fill in places")
    try:  # postings whose list shows no posted date get it from their page, so date windows and "newest" can use them
        if settings.JOB_CACHE_DATE_FILL > 0:
            await fill_dates(cache, settings.JOB_CACHE_DATE_FILL, 10)
    except Exception:
        log.exception("job cache: could not fill in posted dates")
    removed = cache.cleanup()
    return (
        f"saved {filled} descriptions, read {tallies['ok']} employers ({tallies['new']} new postings, {tallies['closed']} closed), "
        f"{tallies['failed']} failed, {tallies['skipped']} left for next time, {removed} old postings removed"
    )


def run_refresh(only_ids: list[int] | None = None, limit: int = 400, max_seconds: float = 1500.0, seed: bool = True) -> str:
    """Reads the employers that are due. Runs in a background thread; only one refresh runs at a time."""
    if not _LOCK.acquire(blocking=False):
        return "a refresh is already running"
    STATE.running, STATE.started, STATE.finished, STATE.summary = True, time.time(), None, ""
    summary = ""
    try:
        if seed:
            try:
                from app.database import SessionLocal

                with SessionLocal() as db:
                    added = seed_from_app(db)
                if added:
                    log.warning("job cache: added %d employers from your saved jobs and results", added)
            except Exception:
                log.exception("job cache: could not read employers from your saved jobs")
        summary = asyncio.run(_refresh_async(only_ids, limit, max_seconds))
    except Exception as exc:
        log.exception("job cache: refresh failed")
        summary = f"stopped by an error: {type(exc).__name__}"
    finally:
        STATE.summary = summary
        STATE.running, STATE.finished = False, time.time()
        _LOCK.release()
    log.warning("job cache: refresh finished: %s", summary)
    return summary


def refresh_in_background(only_ids: list[int] | None = None, seed: bool = True, force: bool = False) -> bool:
    """Starts a refresh without waiting for it. False when one is already running or automatic refreshing is switched off."""
    if _LOCK.locked() or (not force and not settings.JOB_CACHE_AUTO_REFRESH):
        return False
    threading.Thread(target=run_refresh, kwargs={"only_ids": only_ids, "seed": seed}, daemon=True, name="job-cache-refresh").start()
    return True


def status() -> dict[str, Any]:
    cache = JobCache()
    counts = cache.counts()
    return {**counts, "refresh": refresh_state(), "systems": list(SYSTEMS), "disabled": sorted(disabled_systems())}
