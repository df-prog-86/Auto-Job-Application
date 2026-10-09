"""
Readers for the four hiring systems. Each one reads an employer's public job list, the same data that powers the
employer's own careers page, and returns postings in one shape. They only read: no logins, no accounts, nothing is
submitted.

Politeness is built in: the app names itself honestly, spaces out its requests to each site, never asks a site for
more than one thing at a time per employer, and backs off for a long while when a site says "slow down". It never
tries to get around a block.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.services.jobcache.store import PostingIn
from app.services.jobcache.text import pay_midpoint, work_type_from, workday_posted

USER_AGENT = "JobAgent/1.0 (personal job search tool; reads public job lists)"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

SYSTEMS = ("workday", "greenhouse", "lever", "ashby")
WORKDAY_PAGE = 20  # Workday returns at most 20 jobs per request
WORKDAY_MAX_JOBS = 1500  # a very large employer is read up to this many jobs, newest first as Workday lists them
_MIN_GAP = {"workday": 0.6, "greenhouse": 0.3, "lever": 0.3, "ashby": 0.3}  # seconds between requests to one site
_LANG = re.compile(r"[a-z]{2}-[A-Za-z]{2}")


class ReaderError(Exception):
    """A read that did not work. `gone` means the employer's list no longer exists at that address."""

    def __init__(self, message: str, gone: bool = False, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.gone = gone
        self.retry_after = retry_after


@dataclass
class ReadResult:
    postings: list[PostingIn]
    complete: bool = True  # False when only part of a very large list was read: nothing is marked closed from it
    name: str | None = None
    notes: list[str] = field(default_factory=list)


class Throttle:
    """Keeps a minimum gap between requests to the same site, however many employers are being read."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, host: str, gap: float) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            delay = self._last.get(host, 0.0) + gap - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last[host] = time.monotonic()


# ---- employers from addresses ------------------------------------------------------------------------------------

def employer_ref(url: str) -> tuple[str, str] | None:
    """
    (system, identifier) for the employer behind a posting or careers link, or None when it is not one of the four.
    Workday's identifier is "host|tenant|site"; a European Greenhouse or Lever board is written "eu:name".
    """
    parts = urlsplit((url or "").strip())
    host = (parts.hostname or "").lower()
    segs = [p for p in parts.path.split("/") if p]
    if parts.scheme not in ("http", "https") or not host:
        return None
    if host.endswith(".myworkdayjobs.com"):
        if segs and _LANG.fullmatch(segs[0]):
            segs = segs[1:]
        if not segs or segs[0] in ("job", "jobs", "login", "apply"):
            return None
        return "workday", f"{host}|{host.split('.')[0]}|{segs[0]}"
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io", "boards.eu.greenhouse.io"):
        embedded = re.search(r"(?:^|&)for=([\w-]+)", parts.query or "")
        token = embedded.group(1) if embedded else (segs[0] if segs else None)
        if not token or token in ("embed", "jobs"):
            return None
        return "greenhouse", ("eu:" if ".eu." in host else "") + token
    if host in ("jobs.lever.co", "jobs.eu.lever.co"):
        return ("lever", ("eu:" if ".eu." in host else "") + segs[0]) if segs else None
    if host == "jobs.ashbyhq.com":
        return ("ashby", segs[0]) if segs else None
    return None


# ---- fetching ----------------------------------------------------------------------------------------------------

async def _request(client: httpx.AsyncClient, throttle: Throttle, system: str, method: str, url: str, **kwargs: Any) -> Any:
    host = urlsplit(url).hostname or url
    await throttle.wait(host, _MIN_GAP[system])
    try:
        resp = await client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise ReaderError(f"could not reach the site ({type(exc).__name__})") from exc
    if resp.status_code == 429 or resp.status_code == 403:
        wait = resp.headers.get("Retry-After", "")
        raise ReaderError("the site asked us to slow down", retry_after=int(wait) if wait.isdigit() else 6 * 3600)
    if resp.status_code in (404, 410):
        raise ReaderError("that job list was not found", gone=True)
    if resp.status_code != 200:
        raise ReaderError(f"the site answered with an error ({resp.status_code})")
    try:
        return resp.json()
    except ValueError as exc:
        raise ReaderError("the site's answer was not readable") from exc


def _eu(identifier: str) -> tuple[bool, str]:
    return (True, identifier[3:]) if identifier.startswith("eu:") else (False, identifier)


# ---- Greenhouse ---------------------------------------------------------------------------------------------------

def parse_greenhouse(data: Any, token: str) -> list[PostingIn]:
    out: list[PostingIn] = []
    jobs = data.get("jobs") if isinstance(data, dict) else None
    for j in jobs or []:
        if not isinstance(j, dict) or j.get("id") is None or not j.get("title"):
            continue
        loc = (j.get("location") or {}).get("name") if isinstance(j.get("location"), dict) else None
        url = j.get("absolute_url") or ""
        if "greenhouse.io" not in url:  # an employer that embeds its board: use the board's own address for the posting
            url = f"https://job-boards.greenhouse.io/{token}/jobs/{j['id']}"
        posted = _date(j.get("first_published"))
        out.append(
            PostingIn(ext_id=str(j["id"]), title=str(j["title"]).strip(), url=url, location=loc, work_type=work_type_from(None, loc, j["title"]), posted_at=posted)
        )
    return out


async def _read_greenhouse(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    eu, token = _eu(identifier)
    base = f"https://boards-api.{'eu.' if eu else ''}greenhouse.io/v1/boards/{token}"
    data = await _request(client, throttle, "greenhouse", "GET", f"{base}/jobs")
    name = None
    try:
        info = await _request(client, throttle, "greenhouse", "GET", base)
        name = info.get("name") if isinstance(info, dict) else None
    except ReaderError:
        pass
    return ReadResult(parse_greenhouse(data, token), name=name)


# ---- Lever --------------------------------------------------------------------------------------------------------

def parse_lever(data: Any) -> list[PostingIn]:
    out: list[PostingIn] = []
    for j in data if isinstance(data, list) else []:
        if not isinstance(j, dict) or not j.get("id") or not j.get("text"):
            continue
        cats = j.get("categories") if isinstance(j.get("categories"), dict) else {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or []) or None
        pay_text, mid = None, None
        rng = j.get("salaryRange")
        if isinstance(rng, dict) and isinstance(rng.get("min"), (int, float)) and isinstance(rng.get("max"), (int, float)):
            yearly = "year" in str(rng.get("interval", "")).lower() or rng["min"] >= 1000
            cur = str(rng.get("currency") or "USD")
            if yearly:
                pay_text = f"${rng['min']:,.0f} - ${rng['max']:,.0f}" if cur == "USD" else f"{cur} {rng['min']:,.0f} - {rng['max']:,.0f}"
                mid = (rng["min"] + rng["max"]) / 2 if cur == "USD" else None
        created = j.get("createdAt")
        posted = dt.datetime.fromtimestamp(created / 1000, tz=dt.timezone.utc).date() if isinstance(created, (int, float)) and created > 0 else None
        url = j.get("hostedUrl") or f"https://jobs.lever.co/{j.get('id')}"
        out.append(
            PostingIn(
                ext_id=str(j["id"]), title=str(j["text"]).strip(), url=url, location=loc,
                work_type=work_type_from(j.get("workplaceType"), loc, j["text"]), pay_text=pay_text, pay_mid=mid, posted_at=posted,
            )
        )
    return out


async def _read_lever(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    eu, slug = _eu(identifier)
    data = await _request(client, throttle, "lever", "GET", f"https://api.{'eu.' if eu else ''}lever.co/v0/postings/{slug}", params={"mode": "json"})
    return ReadResult(parse_lever(data))


# ---- Ashby --------------------------------------------------------------------------------------------------------

def parse_ashby(data: Any, board: str) -> list[PostingIn]:
    out: list[PostingIn] = []
    jobs = data.get("jobs") if isinstance(data, dict) else None
    for j in jobs or []:
        if not isinstance(j, dict) or not j.get("id") or not j.get("title") or j.get("isListed") is False:
            continue
        loc = j.get("location") if isinstance(j.get("location"), str) else None
        declared = "remote" if j.get("isRemote") is True else j.get("workplaceType")
        comp = j.get("compensation") if isinstance(j.get("compensation"), dict) else {}
        pay_text = comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary")
        pay_text = pay_text if isinstance(pay_text, str) and pay_text.strip() else None
        out.append(
            PostingIn(
                ext_id=str(j["id"]), title=str(j["title"]).strip(), url=j.get("jobUrl") or f"https://jobs.ashbyhq.com/{board}/{j['id']}",
                location=loc, work_type=work_type_from(declared, loc, j["title"]), pay_text=pay_text, pay_mid=pay_midpoint(pay_text),
                posted_at=_date(j.get("publishedAt")),
            )
        )
    return out


async def _read_ashby(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    data = await _request(client, throttle, "ashby", "GET", f"https://api.ashbyhq.com/posting-api/job-board/{identifier}", params={"includeCompensation": "true"})
    return ReadResult(parse_ashby(data, identifier))


# ---- Workday ------------------------------------------------------------------------------------------------------

def parse_workday(data: Any, host: str, site: str) -> list[PostingIn]:
    out: list[PostingIn] = []
    for j in (data.get("jobPostings") if isinstance(data, dict) else None) or []:
        if not isinstance(j, dict) or not j.get("externalPath") or not j.get("title"):
            continue
        path = str(j["externalPath"])
        loc = j.get("locationsText") if isinstance(j.get("locationsText"), str) else None
        out.append(
            PostingIn(
                ext_id=path, title=str(j["title"]).strip(), url=f"https://{host}/en-US/{site}{path}", location=loc,
                work_type=work_type_from(None, loc, j["title"]), posted_at=workday_posted(j.get("postedOn")),
            )
        )
    return out


async def _read_workday(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    try:
        host, tenant, site = identifier.split("|")
    except ValueError as exc:
        raise ReaderError("that Workday address is incomplete", gone=True) from exc
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    postings: list[PostingIn] = []
    total: int | None = None
    complete = False
    for offset in range(0, WORKDAY_MAX_JOBS, WORKDAY_PAGE):
        data = await _request(
            client, throttle, "workday", "POST", url,
            json={"appliedFacets": {}, "limit": WORKDAY_PAGE, "offset": offset, "searchText": ""},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        page = parse_workday(data, host, site)
        if total is None and isinstance(data, dict) and isinstance(data.get("total"), int) and data["total"] > 0:
            total = data["total"]  # Workday only reports the total on the first page
        postings.extend(page)
        if len(page) < WORKDAY_PAGE or (total is not None and offset + WORKDAY_PAGE >= total):
            complete = True  # reached the end of the list
            break
    notes = [] if complete else [f"read the first {len(postings)} of {total or 'many'} jobs"]
    return ReadResult(postings, complete=complete, notes=notes)


# ---- entry point --------------------------------------------------------------------------------------------------

_READERS = {"greenhouse": _read_greenhouse, "lever": _read_lever, "ashby": _read_ashby, "workday": _read_workday}


async def read_employer(system: str, identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    reader = _READERS.get(system)
    if reader is None:
        raise ReaderError(f"no reader for {system}", gone=True)
    return await reader(identifier, client, throttle)


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})


def _date(value: Any) -> dt.date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        day = dt.date.fromisoformat(value[:10])
    except ValueError:
        return None
    return day if day <= dt.date.today() else None
