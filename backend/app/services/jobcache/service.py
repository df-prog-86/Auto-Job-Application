"""
Ties the job cache together: searching it, keeping it up to date, and growing the employer list.

The list of employers grows from three places: the employers behind jobs you saved and results you were shown, links you
paste in the Employers panel, and employers the web search turns up. Reading them is a background job that is polite to
every site (see readers.py); searching the saved copy is instant and costs nothing.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.services.jobcache import matcher
from app.services.jobcache.keys import loose_keys, url_key
from app.services.jobcache.readers import SYSTEMS, ReaderError, Throttle, employer_ref, make_client, read_employer
from app.services.jobcache.store import JobCache, now_ts
from app.services.jobcache.text import fold

log = logging.getLogger("job_cache")

SYSTEM_LABELS = {"workday": "Workday", "greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby"}
CONCURRENT_EMPLOYERS = 4
PRIORITY_HOURS, REGULAR_HOURS = 6.0, 24.0


def disabled_systems() -> set[str]:
    return {s.strip().lower() for s in (settings.JOB_CACHE_DISABLED_SYSTEMS or "").split(",") if s.strip()}


# ---- searching --------------------------------------------------------------------------------------------------

@dataclass
class CacheOutcome:
    items: list[dict[str, Any]] = field(default_factory=list)
    matches: int = 0  # postings that fit and were not already shown or saved
    matches_capped: bool = False  # True when the search read its limit of candidates, so there may be more
    coverage: dict[str, Any] = field(default_factory=dict)


def to_item(scored: matcher.Scored) -> dict[str, Any]:
    r = scored.row
    posted = r.get("posted_at")
    return {
        "title": r["title"],
        "company": r["company"],
        "location": r.get("location"),
        "work_type": r.get("work_type"),
        "salary_text": r.get("pay_text"),
        "posted_at": dt.date.fromisoformat(posted[:10]) if isinstance(posted, str) and len(posted) >= 10 else None,
        "summary": None,
        "url": r["url"],
        "url_key": url_key(r["url"]),
        "grounded": True,  # the employer's own list: as direct as a link gets
        "fit": scored.fit,
        "employer_id": r["eid"],
    }


def search_sync(criteria: Any, known_keys: set[str], extra_titles: list[str] | None, pool: int) -> CacheOutcome:
    cache = JobCache()
    coverage = cache.counts()
    plan = matcher.build_plan(criteria, extra_titles)
    if coverage["postings"] == 0 or not plan.queries:
        return CacheOutcome(coverage=coverage)
    off = disabled_systems()
    rows: list[dict[str, Any]] = []
    for query in matcher.fts_queries(plan) or [None]:
        rows = cache.candidates(query, matcher.like_terms(plan), matcher.CANDIDATE_LIMIT, plan.earliest())
        if len(rows) >= matcher.ENOUGH_TIGHT:
            break
    rows = [r for r in rows if r["ats"] not in off]
    scored = matcher.rank(plan, rows)
    fresh = [s for s in scored if not (loose_keys(s.row["url"]) & known_keys)]
    return CacheOutcome(
        items=[to_item(s) for s in fresh[:pool]],
        matches=len(fresh),
        matches_capped=len(rows) >= matcher.CANDIDATE_LIMIT,
        coverage=coverage,
    )


async def expand_titles(titles: str) -> list[str]:
    """
    A few other titles employers use for the same kind of work, so a search for "revenue cycle manager" also finds
    "manager, patient financial services". One small AI call per new search wording, remembered afterwards; nothing from
    your profile is sent, only the words you typed. Returns [] if the AI is not set up or the answer is unusable.
    """
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


async def search_cache(criteria: Any, known_keys: set[str], pool: int) -> CacheOutcome:
    """Searches the saved employer lists. Fast whatever their size; the only AI use is the one optional title lookup."""
    cache = JobCache()
    counts = await asyncio.to_thread(cache.counts)
    if counts["postings"] == 0:
        return CacheOutcome(coverage=counts)
    extra = await expand_titles(criteria.titles)
    return await asyncio.to_thread(search_sync, criteria, known_keys, extra, pool)


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


class AddEmployerError(Exception):
    """The employer could not be added; the message is safe to show."""


async def add_employer(url: str, company: str | None = None) -> dict[str, Any]:
    ref = employer_ref(url)
    if ref is None:
        raise AddEmployerError("That link isn't from Workday, Greenhouse, Lever or Ashby, so it can't be added yet. Paste a link to one of its job postings or its job list.")
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
    removed = cache.cleanup()
    return (
        f"read {tallies['ok']} employers ({tallies['new']} new postings, {tallies['closed']} closed), "
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
