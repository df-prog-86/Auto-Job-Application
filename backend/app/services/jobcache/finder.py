"""
Find employers by industry and city: the AI web search suggests companies with an office or headquarters in each city, and
CODE then checks every suggestion by reading its real job list. Only employers whose list was read, and has open jobs, are
added. The AI is never trusted on its own: a made-up company, a wrong link or a company on a system we can't read ends up
under "not readable" and is left out.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.discovery.web_search import AGGREGATOR_DOMAINS, _clean, parse_items, search_model, web_plugin
from app.services.jobcache import service
from app.services.jobcache.readers import ReaderError, Throttle, employer_ref, make_client, read_employer
from app.services.jobcache.store import JobCache, now_ts
from app.services.jobcache.text import fold
from app.services.llm.client import LLMClient
from app.services.llm.exceptions import LLMNotConfiguredError

log = logging.getLogger("job_cache")

MAX_CITIES = 5
PER_CITY = 15  # companies asked for per city
MAX_COMPANIES = 60  # checked per request, however many cities
CONCURRENCY = 4
SOURCE = "industry"
# Hiring systems whose public lists can be tried from a company name alone (Workday needs its exact address, so it only
# comes from a link the AI found).
GUESSABLE = ("greenhouse", "lever", "ashby")
_SUFFIXES = frozenset("inc llc ltd corp corporation co company plc the group holdings".split())


@dataclass
class Found:
    name: str
    system: str
    open_jobs: int
    city: str | None = None


@dataclass
class FindOutcome:
    cities: list[str]
    suggested: int = 0
    added: list[Found] = field(default_factory=list)
    already: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)


def clean_cities(cities: list[str]) -> list[str]:
    """The cities as typed, trimmed, without blanks or repeats, at most MAX_CITIES."""
    seen: set[str] = set()
    out: list[str] = []
    for c in cities:
        c = re.sub(r"\s+", " ", (c or "").strip())
        if len(c) >= 2 and fold(c) not in seen:
            seen.add(fold(c))
            out.append(c[:80])
    return out[:MAX_CITIES]


def slug_guesses(company: str) -> list[str]:
    """Addresses a company's name could be written as: "Flatiron Health, Inc." -> flatironhealth, flatiron-health."""
    words = [w for w in fold(company).split() if w not in _SUFFIXES]
    if not words:
        return []
    out = ["".join(words), "-".join(words)]
    return list(dict.fromkeys(s for s in out if len(s) >= 3))


def build_messages(industry: str, city: str) -> list[dict[str, str]]:
    system = (
        "You find employers with web search and report them as JSON. "
        "List real companies and organizations that currently hire and have their headquarters or an office in the city asked "
        "or its greater metro area (the nearby cities and suburbs, for example Cambridge and Quincy for Boston), in the industry asked. Include large and mid-size employers, not only the best known. "
        "For each, give the page of its job list or any one of its job postings on its own careers site or hiring system "
        "(Workday, Greenhouse, Lever, Ashby, or its own site) as careers_url, or null if you did not find one. "
        "Never use a job board, recruiter, staffing agency or news page as careers_url. "
        "Use only companies you found in results; never invent a company or a link. Skip duplicates. "
        "Return fewer items rather than weak ones; if none match, return []. "
        "Reply with ONLY a JSON array. Item keys: company, careers_url, city (the town or city where its office or headquarters is)."
    )
    user = f"Find up to {PER_CITY} employers.\n- Industry: {industry}\n- City: {city}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def _suggest(industry: str, city: str, model: str) -> list[dict[str, Any]]:
    plugin = web_plugin(10)
    plugin["exclude_domains"] = sorted(AGGREGATOR_DOMAINS)
    result = await LLMClient().chat_completion(
        model=model,
        messages=build_messages(industry, city),
        temperature=0.0,
        max_tokens=2500,
        extra={"plugins": [plugin]},
        timeout=150.0,
    )
    items: list[dict[str, Any]] = []
    for raw in parse_items(result.content):
        company = _clean(raw.get("company"), 200)
        if not company:
            continue
        link = _clean(raw.get("careers_url"), 1000)
        items.append({"company": company, "url": link if link and link.lower().startswith(("http://", "https://")) else None, "city": city})
    log.warning("job cache: employer finder [%s, %s]: AI suggested %d companies", industry, city, len(items))
    return items


async def _read_and_add(cache: JobCache, system: str, identifier: str, company: str, industry: str, client: Any, throttle: Throttle) -> tuple[str, dict[str, Any]] | None:
    """Reads one job list. ("added", row) when new and has open jobs, ("already", row) when saved before, None when it can't be used."""
    eid, created = await asyncio.to_thread(cache.upsert_employer, system, identifier, company, SOURCE, industry)
    if not created:
        row = await asyncio.to_thread(cache.get_employer, eid)
        return ("already", row) if row else None
    try:
        result = await read_employer(system, identifier, client, throttle)
    except ReaderError:
        await asyncio.to_thread(cache.delete_employer, eid)
        return None
    except Exception:
        log.exception("job cache: employer finder could not read %s %s", system, identifier)
        await asyncio.to_thread(cache.delete_employer, eid)
        return None
    if not result.postings:  # an empty or placeholder list is no use
        await asyncio.to_thread(cache.delete_employer, eid)
        return None
    await asyncio.to_thread(cache.apply_refresh, eid, result.postings, now_ts(), service.PRIORITY_HOURS, result.complete)
    row = await asyncio.to_thread(cache.get_employer, eid)
    return ("added", row) if row else None


async def _check_company(item: dict[str, Any], industry: str, cache: JobCache, client: Any, throttle: Throttle, off: set[str]) -> tuple[str, dict[str, Any] | None]:
    company = item["company"]
    ref = employer_ref(item["url"]) if item.get("url") else None
    if ref and ref[0] not in off:
        got = await _read_and_add(cache, ref[0], ref[1], company, industry, client, throttle)
        if got:
            return got
    for system in GUESSABLE:
        if system in off:
            continue
        for slug in slug_guesses(company):
            got = await _read_and_add(cache, system, slug, company, industry, client, throttle)
            if got:
                return got
    return "unreadable", None


async def find_employers(industry: str, cities: list[str]) -> FindOutcome:
    """The whole feature. Raises LLMNotConfiguredError when no AI connection is set up and the search error when every city failed."""
    industry = re.sub(r"\s+", " ", industry.strip())[:120]
    cities = clean_cities(cities)
    outcome = FindOutcome(cities=cities)
    model = search_model()
    if not model:
        raise LLMNotConfiguredError("No LLM provider configured (PRIMARY_FAST_MODEL unset).")
    results = await asyncio.gather(*(_suggest(industry, c, model) for c in cities), return_exceptions=True)
    batches = [r for r in results if isinstance(r, list)]
    if not batches:
        raise next(r for r in results if isinstance(r, BaseException))
    for city, r in zip(cities, results):
        if isinstance(r, BaseException):
            log.warning("job cache: employer finder [%s]: search failed: %s: %s", city, type(r).__name__, r)

    unique: dict[str, dict[str, Any]] = {}
    for batch in batches:
        for item in batch:
            key = fold(item["company"])
            if key and key not in unique:
                unique[key] = item
            elif key and not unique[key].get("url") and item.get("url"):
                unique[key]["url"] = item["url"]
    items = list(unique.values())[:MAX_COMPANIES]
    outcome.suggested = len(items)

    cache = JobCache()
    off = service.disabled_systems()
    throttle = Throttle()
    gate = asyncio.Semaphore(CONCURRENCY)
    async with make_client() as client:

        async def one(item: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
            async with gate:
                try:
                    status, row = await _check_company(item, industry, cache, client, throttle, off)
                except Exception:
                    log.exception("job cache: employer finder failed on %s", item["company"])
                    status, row = "unreadable", None
                return item, status, row

        checked = await asyncio.gather(*(one(i) for i in items))
    for item, status, row in checked:
        if status == "added" and row:
            outcome.added.append(Found(name=row["name"], system=row["ats"], open_jobs=row["open_count"], city=item.get("city")))
        elif status == "already":
            outcome.already.append(item["company"])
        else:
            outcome.unreadable.append(item["company"])
    outcome.added.sort(key=lambda f: -f.open_jobs)
    log.warning(
        "job cache: employer finder [%s | %s]: %d suggested, %d added, %d already saved, %d not readable",
        industry, ", ".join(cities), outcome.suggested, len(outcome.added), len(outcome.already), len(outcome.unreadable),
    )
    return outcome
