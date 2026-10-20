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
from urllib.parse import parse_qs, urlsplit

import httpx

from app.services.jobcache.store import PostingIn
from app.services.jobcache.text import html_to_text, is_vague_place, location_from_text, pay_from_text, pay_midpoint, work_type_from, workday_posted

USER_AGENT = "JobAgent/1.0 (personal job search tool; reads public job lists)"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

SYSTEMS = ("workday", "greenhouse", "lever", "ashby", "smartrecruiters", "breezy", "workable", "bamboohr", "pinpoint", "jazzhr", "jobvite", "oracle", "icims", "taleo", "phenom", "successfactors", "dayforce", "kpmg", "deloitte", "talentbrew", "jibe")
WORKDAY_PAGE = 20  # Workday returns at most 20 jobs per request
WORKDAY_MAX_JOBS = 4000  # a very large employer is read up to this many jobs, newest first as Workday lists them (IQVIA hit the old 1,500 limit)
SMARTRECRUITERS_PAGE = 100  # postings per request from the public Posting API
SMARTRECRUITERS_MAX_JOBS = 2000
_MIN_GAP = {
    "workday": 0.6, "greenhouse": 0.3, "lever": 0.3, "ashby": 0.3, "smartrecruiters": 0.4,
    "breezy": 0.5, "workable": 0.5, "bamboohr": 0.5, "pinpoint": 0.5, "jazzhr": 0.8, "jobvite": 0.8, "oracle": 0.6, "icims": 1.0, "taleo": 1.0, "phenom": 0.6, "successfactors": 1.0, "dayforce": 0.6, "kpmg": 1.0, "deloitte": 1.0, "talentbrew": 1.0, "jibe": 1.0,
}  # seconds between requests to one site
JIBE_SITES = {"careers.amd.com"}  # Jibe (iCIMS) career sites with a public /api/jobs list, each added by hand once it has been checked
TALENTBREW_SITES = {"careers.unitedhealthgroup.com"}  # TalentBrew (Radancy) career sites, each added by hand once it has been checked
PHENOM_SITES = {"careers.bcg.com"}  # Phenom career sites differ in their settings, so each one is added by hand once it has been checked
SUCCESSFACTORS_SITES = {"careers.ey.com"}  # EY lists the whole world; only its US jobs are read (see SUCCESSFACTORS_COUNTRY)
SUCCESSFACTORS_COUNTRY = {"careers.ey.com": "US"}
SUCCESSFACTORS_PAGE = 25
SUCCESSFACTORS_MAX_JOBS = 4000
PHENOM_PAGE = 50
PHENOM_MAX_JOBS = 3000
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
    (system, identifier) for the employer behind a posting or careers link, or None when it is not one of the five hiring systems.
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
        site = segs[0]
        # a bare language ("en", "es"), a file ("robots.txt") or a Workday system folder is never a career site name
        if "." in site or re.fullmatch(r"[a-z]{2}", site) or site.lower() in ("wday", "assets", "favicon", "static", "sitemap", "pages", "cxs"):
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
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com"):
        return ("smartrecruiters", segs[0]) if segs and segs[0].lower() not in ("search", "login", "job", "jobs", "oga") else None
    if host in ("www.smartrecruiters.com", "smartrecruiters.com") and len(segs) >= 2 and segs[1][:1].isdigit():
        return "smartrecruiters", segs[0]  # an application link: smartrecruiters.com/<company>/<id>-<title>
    sub = host.split(".")[0]
    if host.endswith(".breezy.hr") and sub not in ("www", "app", "api"):
        return "breezy", sub
    if host == "apply.workable.com" and segs and segs[0] not in ("j", "api", "jobs", "tos", "privacy"):
        return "workable", segs[0]
    if host.endswith(".bamboohr.com") and sub not in ("www", "app", "api", "documentation"):
        return "bamboohr", sub
    if host.endswith(".pinpointhq.com") and sub not in ("www", "app", "api", "developers"):
        return "pinpoint", sub
    if host.endswith(".applytojob.com") and sub not in ("www", "app", "api"):
        return "jazzhr", sub
    if host == "jobs.jobvite.com" and segs and segs[0].lower() not in ("careers", "search", "job", "jobs", "api"):
        return "jobvite", segs[0]
    if host.endswith(".taleo.net") and segs:
        q = parse_qs(parts.query or "")
        org, cws = (q.get("org") or [""])[0], (q.get("cws") or [""])[0]
        return ("taleo", f"{host}|{segs[0]}|{org}|{cws}") if org and cws else None
    if host in JIBE_SITES:
        return "jibe", host
    if host in TALENTBREW_SITES and segs and segs[0] in ("job", "search-jobs"):
        return "talentbrew", host
    if host in PHENOM_SITES:
        return "phenom", host
    if host in SUCCESSFACTORS_SITES and segs and segs[0] == "ey":
        return "successfactors", f"{host}|{segs[0]}"
    if host == "jobs.dayforcehcm.com" and len(segs) >= 3 and _LANG.fullmatch(segs[0]):
        return "dayforce", f"{segs[1]}|{segs[2]}|{segs[0]}"
    if host in ("www.kpmguscareers.com", "kpmguscareers.com") and segs and segs[0] in ("job-search", "jobdetail"):
        return "kpmg", "www.kpmguscareers.com"
    if host == "apply.deloitte.com" and any(x.lower() in ("searchjobs", "jobdetail") for x in segs):
        return "deloitte", "apply.deloitte.com"
    if host.endswith(".icims.com") and sub not in ("www", "app", "api", "login", "careers", "jobs"):
        return "icims", host
    if host.endswith(".oraclecloud.com") and ".fa." in host and "sites" in segs[:-1]:
        site = segs[segs.index("sites") + 1]
        return "oracle", f"{host}|{site}"
    return None


# ---- fetching ----------------------------------------------------------------------------------------------------

# The only sites a reader may ever contact. A list address is built from text taken out of a link (a company name, a subdomain),
# so this is checked once, here, for every reader: whatever the text said, the request goes to one of these hiring systems.
READER_HOST_SUFFIXES = (
    ".greenhouse.io", ".lever.co", ".ashbyhq.com", ".smartrecruiters.com", ".myworkdayjobs.com", ".breezy.hr", ".workable.com",
    ".bamboohr.com", ".pinpointhq.com", ".applytojob.com", ".jobvite.com", ".oraclecloud.com", ".icims.com", ".taleo.net",
    ".dayforcehcm.com", ".kpmguscareers.com", "apply.deloitte.com",
)


def reader_url_allowed(url: str) -> bool:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password or (parts.port not in (None, 443)):
        return False
    if any(bad in parts.path.lower() for bad in ("..", "%2e", "%2f", "%5c", "\\")) or any(c.isspace() for c in url):
        return False
    return host in PHENOM_SITES or host in TALENTBREW_SITES or host in JIBE_SITES or host in SUCCESSFACTORS_SITES or host.endswith(READER_HOST_SUFFIXES) or any(host == s[1:] for s in READER_HOST_SUFFIXES)


async def _request(client: httpx.AsyncClient, throttle: Throttle, system: str, method: str, url: str, text: bool = False, **kwargs: Any) -> Any:
    if not reader_url_allowed(url):
        raise ReaderError("that address is not a hiring-system address we read", gone=True)
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
    if text:
        return resp.text
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
        body = html_to_text(j.get("content")) if j.get("content") else ""
        pay_text, mid = pay_from_text(body)
        if is_vague_place(loc):
            loc = location_from_text(body) or loc
        out.append(
            PostingIn(
                ext_id=str(j["id"]), title=str(j["title"]).strip(), url=url, location=loc, work_type=work_type_from(None, loc, j["title"]),
                pay_text=pay_text, pay_mid=mid, posted_at=posted, description=body or None,
            )
        )
    return out


async def _read_greenhouse(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    eu, token = _eu(identifier)
    base = f"https://boards-api.{'eu.' if eu else ''}greenhouse.io/v1/boards/{token}"
    data = await _request(client, throttle, "greenhouse", "GET", f"{base}/jobs", params={"content": "true"})  # with the text, so pay written in it can be read
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
        body = " \n".join(str(j.get(k) or "") for k in ("descriptionPlain", "additionalPlain"))
        body += " \n" + " \n".join(html_to_text(x.get("content")) for x in (j.get("lists") or []) if isinstance(x, dict))
        if pay_text is None:  # no pay field: look in the posting's own words
            pay_text, mid = pay_from_text(f"{j.get('salaryDescriptionPlain') or ''} {body}")
        if is_vague_place(loc):
            loc = location_from_text(body) or loc
        created = j.get("createdAt")
        posted = dt.datetime.fromtimestamp(created / 1000, tz=dt.timezone.utc).date() if isinstance(created, (int, float)) and created > 0 else None
        url = j.get("hostedUrl") or f"https://jobs.lever.co/{j.get('id')}"
        out.append(
            PostingIn(
                ext_id=str(j["id"]), title=str(j["text"]).strip(), url=url, location=loc,
                work_type=work_type_from(j.get("workplaceType"), loc, j["text"]), pay_text=pay_text, pay_mid=mid, posted_at=posted, description=body.strip() or None,
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
        mid = pay_midpoint(pay_text)
        body = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml"))
        if pay_text is None:
            pay_text, mid = pay_from_text(body)
        if is_vague_place(loc):
            loc = location_from_text(body) or loc
        out.append(
            PostingIn(
                ext_id=str(j["id"]), title=str(j["title"]).strip(), url=j.get("jobUrl") or f"https://jobs.ashbyhq.com/{board}/{j['id']}",
                location=loc, work_type=work_type_from(declared, loc, j["title"]), pay_text=pay_text, pay_mid=mid,
                posted_at=_date(j.get("publishedAt")), description=body or None,
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


WORKDAY_WINDOW = 2000  # Workday answers only the first 2,000 jobs of any one search, however many the employer has


def workday_slices(data: Any) -> list[tuple[str, list[tuple[str, int]]]]:
    """The category filters Workday offers with its first answer: [(filter name, [(value id, jobs)])], one entry per kind of filter."""
    out: list[tuple[str, list[tuple[str, int]]]] = []

    def walk(facet: Any) -> None:
        if not isinstance(facet, dict) or not isinstance(facet.get("values"), list):
            return
        leaves = [(str(v["id"]), int(v["count"])) for v in facet["values"] if isinstance(v, dict) and v.get("id") and isinstance(v.get("count"), int)]
        if leaves and isinstance(facet.get("facetParameter"), str):
            out.append((facet["facetParameter"], leaves))
        for v in facet["values"]:
            if isinstance(v, dict) and isinstance(v.get("values"), list):
                walk(v)

    for f in (data.get("facets") if isinstance(data, dict) else None) or []:
        walk(f)
    return out


async def _workday_window(client: httpx.AsyncClient, throttle: Throttle, url: str, host: str, site: str, facets: dict[str, list[str]]) -> tuple[list[PostingIn], int | None, Any, bool]:
    """One search read page by page up to Workday's window: (postings, reported total, first answer, True when the list ended inside the window)."""
    postings: list[PostingIn] = []
    total: int | None = None
    first: Any = None
    for offset in range(0, WORKDAY_MAX_JOBS, WORKDAY_PAGE):
        data = await _request(
            client, throttle, "workday", "POST", url,
            json={"appliedFacets": facets, "limit": WORKDAY_PAGE, "offset": offset, "searchText": ""},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        first = data if first is None else first
        page = parse_workday(data, host, site)
        if total is None and isinstance(data, dict) and isinstance(data.get("total"), int) and data["total"] > 0:
            total = data["total"]  # Workday only reports the total on the first page
        postings.extend(page)
        if len(page) < WORKDAY_PAGE or (total is not None and offset + WORKDAY_PAGE >= total):
            return postings, total, first, True
    return postings, total, first, False


async def _read_workday(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    try:
        host, tenant, site = identifier.split("|")
    except ValueError as exc:
        raise ReaderError("that Workday address is incomplete", gone=True) from exc
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    postings, total, first, ended = await _workday_window(client, throttle, url, host, site, {})
    if ended and len(postings) != WORKDAY_WINDOW:
        return ReadResult(postings)  # the list ended on its own, short of Workday's 2,000 cutoff: read in full
    # A list that stopped at exactly 2,000 (or ran past our own limit) may be cut off. Read it again one category at a time (each is smaller than the window) and join.
    groups = [(name, vals) for name, vals in workday_slices(first) if vals and all(c < WORKDAY_WINDOW for _i, c in vals)]
    if not groups:
        return ReadResult(postings, complete=False, notes=[f"read the first {len(postings)} of {total or 'many'} jobs; no category filter to read the rest"])
    name, vals = max(groups, key=lambda g: (sum(c for _i, c in g[1]), -len(g[1])))  # the filter that covers the most jobs
    by_id = {p.ext_id: p for p in postings}
    all_ended = True
    for value_id, _count in vals:
        got, _t, _f, done = await _workday_window(client, throttle, url, host, site, {name: [value_id]})
        all_ended = all_ended and done
        for p in got:
            by_id.setdefault(p.ext_id, p)
    covered = sum(c for _i, c in vals)
    complete = all_ended and covered >= 0.95 * (total or covered)
    notes = [] if complete else [f"read {len(by_id)} of {total or 'many'} jobs by {name}"]
    return ReadResult(list(by_id.values()), complete=complete, notes=notes)


# ---- SmartRecruiters ----------------------------------------------------------------------------------------------

ISO_COUNTRIES = {
    "AD": "Andorra", "AE": "United Arab Emirates", "AF": "Afghanistan", "AL": "Albania", "AM": "Armenia", "AO": "Angola", "AR": "Argentina",
    "AT": "Austria", "AU": "Australia", "AZ": "Azerbaijan", "BA": "Bosnia", "BD": "Bangladesh", "BE": "Belgium", "BG": "Bulgaria",
    "BH": "Bahrain", "BM": "Bermuda", "BO": "Bolivia", "BR": "Brazil", "BS": "Bahamas", "BY": "Belarus", "CA": "Canada",
    "CH": "Switzerland", "CI": "Ivory Coast", "CL": "Chile", "CM": "Cameroon", "CN": "China", "CO": "Colombia", "CR": "Costa Rica",
    "CY": "Cyprus", "CZ": "Czech Republic", "DE": "Germany", "DK": "Denmark", "DO": "Dominican Republic", "DZ": "Algeria",
    "EC": "Ecuador", "EE": "Estonia", "EG": "Egypt", "ES": "Spain", "ET": "Ethiopia", "FI": "Finland", "FR": "France",
    "GB": "United Kingdom", "UK": "United Kingdom", "GE": "Republic of Georgia", "GH": "Ghana", "GR": "Greece", "GT": "Guatemala",
    "HK": "Hong Kong", "HN": "Honduras", "HR": "Croatia", "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland", "IL": "Israel",
    "IN": "India", "IQ": "Iraq", "IR": "Iran", "IS": "Iceland", "IT": "Italy", "JM": "Jamaica", "JO": "Jordan", "JP": "Japan",
    "KE": "Kenya", "KR": "South Korea", "KW": "Kuwait", "KZ": "Kazakhstan", "LB": "Lebanon", "LK": "Sri Lanka", "LT": "Lithuania",
    "LU": "Luxembourg", "LV": "Latvia", "MA": "Morocco", "MD": "Moldova", "ME": "Montenegro", "MK": "North Macedonia", "MT": "Malta",
    "MX": "Mexico", "MY": "Malaysia", "NG": "Nigeria", "NI": "Nicaragua", "NL": "Netherlands", "NO": "Norway", "NP": "Nepal",
    "NZ": "New Zealand", "OM": "Oman", "PA": "Panama", "PE": "Peru", "PH": "Philippines", "PK": "Pakistan", "PL": "Poland",
    "PT": "Portugal", "PY": "Paraguay", "QA": "Qatar", "RO": "Romania", "RS": "Serbia", "RU": "Russia", "SA": "Saudi Arabia",
    "SE": "Sweden", "SG": "Singapore", "SI": "Slovenia", "SK": "Slovakia", "SN": "Senegal", "SV": "El Salvador", "TH": "Thailand",
    "TN": "Tunisia", "TR": "Turkey", "TT": "Trinidad", "TW": "Taiwan", "TZ": "Tanzania", "UA": "Ukraine", "UG": "Uganda",
    "UY": "Uruguay", "UZ": "Uzbekistan", "VE": "Venezuela", "VN": "Vietnam", "ZA": "South Africa",
}  # two-letter country codes written out, because "CA", "IN", "CO" and "MA" are also US state codes


def parse_smartrecruiters(data: Any, identifier: str) -> list[PostingIn]:
    """SmartRecruiters' public Posting API: {"totalFound": n, "content": [{id, name, releasedDate, location: {city, region, country, remote}, company}]}."""
    out: list[PostingIn] = []
    for j in (data.get("content") if isinstance(data, dict) else None) or []:
        if not isinstance(j, dict) or not j.get("id") or not j.get("name"):
            continue
        loc_obj = j.get("location") if isinstance(j.get("location"), dict) else {}
        city, region, country = (str(loc_obj.get(k) or "").strip() for k in ("city", "region", "country"))
        parts = [city, region] if country.lower() in ("us", "usa", "") else [city, region, ISO_COUNTRIES.get(country.upper(), country.upper())]
        loc = ", ".join(p for p in parts if p) or ("Remote" if loc_obj.get("remote") is True else None)
        declared = "remote" if loc_obj.get("remote") is True else "hybrid" if loc_obj.get("hybrid") is True else None
        company = j.get("company") if isinstance(j.get("company"), dict) else {}
        ident = str(company.get("identifier") or identifier)
        title = str(j["name"]).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        out.append(
            PostingIn(
                ext_id=str(j["id"]), title=title, url=f"https://jobs.smartrecruiters.com/{ident}/{j['id']}" + (f"-{slug}" if slug else ""),
                location=loc, work_type=work_type_from(declared, loc, title), posted_at=_date(j.get("releasedDate")),
            )
        )
    return out


async def _sr_pages(identifier: str, client: httpx.AsyncClient, throttle: Throttle, extra: dict | None = None):
    """Read one SmartRecruiters list (optionally filtered, e.g. country=us) up to the job limit. Returns (postings, name, complete)."""
    url = f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings"
    postings: list[PostingIn] = []
    name: str | None = None
    complete = False
    for offset in range(0, SMARTRECRUITERS_MAX_JOBS, SMARTRECRUITERS_PAGE):
        params = {"limit": SMARTRECRUITERS_PAGE, "offset": offset, **(extra or {})}
        data = await _request(client, throttle, "smartrecruiters", "GET", url, params=params)
        content = data.get("content") if isinstance(data, dict) else None
        page = parse_smartrecruiters(data, identifier)
        if name is None and content:
            first = content[0].get("company") if isinstance(content[0], dict) else None
            if isinstance(first, dict) and isinstance(first.get("name"), str) and first["name"].strip():
                name = first["name"].strip()
        postings.extend(page)
        total = data.get("totalFound") if isinstance(data, dict) else None
        if len(content or []) < SMARTRECRUITERS_PAGE or (isinstance(total, int) and offset + SMARTRECRUITERS_PAGE >= total):
            complete = True
            break
    return postings, name, complete


async def _read_smartrecruiters(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    postings, name, complete = await _sr_pages(identifier, client, throttle)
    notes = [] if complete else [f"read the first {len(postings)} jobs"]
    if not complete:
        # A very large employer: the list is cut off, so also read its US jobs on their own (the API filters by country)
        # and add any the first pass missed. If this extra read fails, the first pass stands.
        try:
            us, _n, _done = await _sr_pages(identifier, client, throttle, {"country": "us"})
            seen = {p.ext_id for p in postings}
            extra = [p for p in us if p.ext_id not in seen]
            postings.extend(extra)
            notes = [f"read the first {len(postings) - len(extra)} jobs, plus {len(extra)} more US jobs"]
            complete = False  # the full list is still cut off, so never treat it as complete
        except Exception:
            pass
    return ReadResult(postings, complete=complete, name=name, notes=notes)


# ---- Breezy HR ----------------------------------------------------------------------------------------------------

def parse_breezy(data: Any, sub: str) -> list[PostingIn]:
    """Breezy's public list (https://<name>.breezy.hr/json): a list of {id, name, url, published_date, location: {name, is_remote}, salary}."""
    out: list[PostingIn] = []
    for j in data if isinstance(data, list) else []:
        if not isinstance(j, dict) or not j.get("id") or not j.get("name"):
            continue
        loc_obj = j.get("location") if isinstance(j.get("location"), dict) else {}
        loc = loc_obj.get("name") if isinstance(loc_obj.get("name"), str) and loc_obj.get("name").strip() else None
        salary = j.get("salary") if isinstance(j.get("salary"), str) and re.search(r"\d", j.get("salary") or "") else None
        title = str(j["name"]).strip()
        out.append(
            PostingIn(
                ext_id=str(j["id"]), title=title, url=str(j.get("url") or f"https://{sub}.breezy.hr/p/{j.get('friendly_id') or j['id']}"),
                location=loc, work_type=work_type_from("remote" if loc_obj.get("is_remote") is True else None, loc, title),
                pay_text=salary, pay_mid=pay_midpoint(salary), posted_at=_date(j.get("published_date")),
            )
        )
    return out


async def _read_breezy(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    data = await _request(client, throttle, "breezy", "GET", f"https://{identifier}.breezy.hr/json")
    if not isinstance(data, list):
        raise ReaderError("the site's answer was not what we expected")
    return ReadResult(parse_breezy(data, identifier))


# ---- Workable -----------------------------------------------------------------------------------------------------

def parse_workable(data: Any, slug: str) -> list[PostingIn]:
    """Workable's public widget list: {"name", "jobs": [{title, shortcode, url, city, state, country, telecommuting, published_on}]}."""
    out: list[PostingIn] = []
    for j in (data.get("jobs") if isinstance(data, dict) else None) or []:
        if not isinstance(j, dict) or not j.get("title") or not (j.get("shortcode") or j.get("url")):
            continue
        city, state, country = (str(j.get(k) or "").strip() for k in ("city", "state", "country"))
        parts = [city, state] if country.lower() in ("united states", "us", "usa", "") else [city, state, country]
        loc = ", ".join(p for p in parts if p) or None
        title = str(j["title"]).strip()
        code = str(j.get("shortcode") or j.get("code") or j.get("url"))
        url = j.get("url") or j.get("shortlink") or f"https://apply.workable.com/{slug}/j/{code}/"
        out.append(
            PostingIn(
                ext_id=code, title=title, url=str(url), location=loc,
                work_type=work_type_from("remote" if j.get("telecommuting") is True else None, loc, title),
                posted_at=_date(j.get("published_on") or j.get("created_at")),
                description=html_to_text(j.get("description")) or None,  # the list carries the text when asked for details
            )
        )
    return out


async def _read_workable(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    data = await _request(client, throttle, "workable", "GET", f"https://apply.workable.com/api/v1/widget/accounts/{identifier}?details=true")
    if not isinstance(data, dict) or "jobs" not in data:
        raise ReaderError("the site's answer was not what we expected")
    name = data.get("name") if isinstance(data.get("name"), str) and data["name"].strip() else None
    return ReadResult(parse_workable(data, identifier), name=name)


# ---- BambooHR -----------------------------------------------------------------------------------------------------

def parse_bamboohr(data: Any, sub: str) -> list[PostingIn]:
    """BambooHR's public list (https://<name>.bamboohr.com/careers/list): {"meta": {"totalCount"}, "result": [{id, jobOpeningName, location: {city, state}, isRemote}]}."""
    out: list[PostingIn] = []
    for j in (data.get("result") if isinstance(data, dict) else None) or []:
        if not isinstance(j, dict) or j.get("id") is None or not j.get("jobOpeningName"):
            continue
        loc_obj = j.get("location") if isinstance(j.get("location"), dict) else {}
        loc = ", ".join(str(loc_obj.get(k)).strip() for k in ("city", "state") if loc_obj.get(k)) or None
        title = str(j["jobOpeningName"]).strip()
        out.append(
            PostingIn(
                ext_id=str(j["id"]), title=title, url=f"https://{sub}.bamboohr.com/careers/{j['id']}", location=loc,
                work_type=work_type_from("remote" if j.get("isRemote") is True else None, loc, title),
            )
        )
    return out


async def _read_bamboohr(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    data = await _request(client, throttle, "bamboohr", "GET", f"https://{identifier}.bamboohr.com/careers/list")
    if not isinstance(data, dict) or "result" not in data:
        raise ReaderError("the site's answer was not what we expected")
    return ReadResult(parse_bamboohr(data, identifier))


# ---- Pinpoint -----------------------------------------------------------------------------------------------------

def _pinpoint_pay(j: dict[str, Any]) -> tuple[str | None, float | None]:
    if not j.get("compensation_visible", True):
        return None, None
    lo, hi = j.get("compensation_minimum"), j.get("compensation_maximum")
    text = j.get("compensation") if isinstance(j.get("compensation"), str) and re.search(r"\d", j.get("compensation") or "") else None
    if text:
        return text, pay_midpoint(text)
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and hi > 0 and str(j.get("compensation_frequency") or "").lower() in ("year", "yearly", "annual", "annually"):
        return f"${lo:,.0f} - ${hi:,.0f} / year", (lo + hi) / 2
    return None, None


def parse_pinpoint(data: Any, sub: str) -> list[PostingIn]:
    """Pinpoint's public list (https://<name>.pinpointhq.com/postings.json): {"data": [{id, title, url, location: {name, city, province}, workplace_type, compensation...}]}."""
    out: list[PostingIn] = []
    for j in (data.get("data") if isinstance(data, dict) else None) or []:
        if not isinstance(j, dict) or j.get("id") is None or not j.get("title"):
            continue
        loc_obj = j.get("location") if isinstance(j.get("location"), dict) else {}
        loc = loc_obj.get("name") if isinstance(loc_obj.get("name"), str) and loc_obj.get("name").strip() else None
        if not loc:
            loc = ", ".join(str(loc_obj.get(k)).strip() for k in ("city", "province") if loc_obj.get(k)) or None
        title = str(j["title"]).strip()
        url = j.get("url") if isinstance(j.get("url"), str) and j["url"].startswith("http") else f"https://{sub}.pinpointhq.com/en/postings/{j['id']}"
        declared = str(j.get("workplace_type") or j.get("workplace_type_text") or "").lower() or None
        if declared and declared.replace("-", "").replace("_", "") == "onsite":
            declared = "onsite"
        pay_text, mid = _pinpoint_pay(j)
        out.append(
            PostingIn(
                ext_id=str(j["id"]), title=title, url=url, location=loc, work_type=work_type_from(declared, loc, title),
                pay_text=pay_text, pay_mid=mid, posted_at=_date(j.get("published_at") or j.get("created_at")),
            )
        )
    return out


async def _read_pinpoint(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    data = await _request(client, throttle, "pinpoint", "GET", f"https://{identifier}.pinpointhq.com/postings.json")
    if not isinstance(data, dict) or "data" not in data:
        raise ReaderError("the site's answer was not what we expected")
    return ReadResult(parse_pinpoint(data, identifier))


# ---- JazzHR (page reading) ----------------------------------------------------------------------------------------

_TAGS = re.compile(r"<[^>]+>")
_NO_JOBS = re.compile(r"no (?:current |open |available )?(?:job|position|opening)s?|currently (?:no|not)|0 (?:open )?jobs", re.I)


def _plain(fragment: str) -> str:
    import html as _html

    return re.sub(r"\s+", " ", _html.unescape(_TAGS.sub(" ", fragment))).strip()


def parse_jazzhr(page: Any, sub: str) -> list[PostingIn]:
    """JazzHR's careers page (https://<name>.applytojob.com/apply): each opening is a link to /apply/<code>/<title> with its place beside it."""
    html = page if isinstance(page, str) else ""
    out: list[PostingIn] = []
    seen: set[str] = set()
    for m in re.finditer(r'<a[^>]+href="(https?://[^"]*applytojob\.com/apply/([A-Za-z0-9]{6,})(?:/[^"]*)?)"[^>]*>(.*?)</a>', html, re.S):
        url, code, inner = m.group(1), m.group(2), _plain(m.group(3))
        if code in seen or not inner or inner.lower() in ("apply", "apply now", "view", "view details", "learn more"):
            continue
        seen.add(code)
        tail = html[m.end(): m.end() + 700]
        end = tail.find("</li>")
        marker = re.search(r'fa-map-marker[^>]*>\s*(?:</i>)?\s*([^<]+)', tail[: end if end > 0 else 700] + "</li>") or re.search(r'fa-map-marker[^>]*>\s*(?:</i>)?\s*([^<]+)', tail)
        loc = _plain(marker.group(1)) if marker else None
        out.append(PostingIn(ext_id=code, title=inner, url=url.split("?")[0], location=loc or None, work_type=work_type_from(None, loc, inner)))
    return out


async def _read_jazzhr(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    page = await _request(client, throttle, "jazzhr", "GET", f"https://{identifier}.applytojob.com/apply", text=True, headers={"Accept": "text/html"})
    postings = parse_jazzhr(page, identifier)
    if not postings and not _NO_JOBS.search(_plain(page)):
        raise ReaderError("we couldn't make sense of that careers page")
    return ReadResult(postings)


# ---- Jobvite (page reading) ---------------------------------------------------------------------------------------

def parse_jobvite(page: Any, slug: str) -> list[PostingIn]:
    """Jobvite's careers page (https://jobs.jobvite.com/<name>/jobs): each opening is a link to /<name>/job/<code> with its place in the next cell."""
    html = page if isinstance(page, str) else ""
    out: list[PostingIn] = []
    seen: set[str] = set()
    for m in re.finditer(r'<a[^>]+href="((?:https?://jobs\.jobvite\.com)?/[^"/]+/job/([A-Za-z0-9]+)[^"]*)"[^>]*>(.*?)</a>', html, re.S):
        href, code, inner = m.group(1), m.group(2), _plain(m.group(3))
        if code in seen or not inner or inner.lower() in ("apply", "apply now", "view", "learn more"):
            continue
        seen.add(code)
        tail = html[m.end(): m.end() + 800]
        loc_m = re.search(r'jv-job-list-location[^>]*>(.*?)</(?:td|div|span|p)>', tail, re.S)
        loc = _plain(loc_m.group(1)) if loc_m else None
        url = href if href.startswith("http") else f"https://jobs.jobvite.com{href}"
        out.append(PostingIn(ext_id=code, title=inner, url=url.split("?")[0], location=loc or None, work_type=work_type_from(None, loc, inner)))
    return out


async def _read_jobvite(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    page = await _request(client, throttle, "jobvite", "GET", f"https://jobs.jobvite.com/{identifier}/jobs", text=True, headers={"Accept": "text/html"})
    postings = parse_jobvite(page, identifier)
    if not postings and not _NO_JOBS.search(_plain(page)):
        raise ReaderError("we couldn't make sense of that careers page")
    return ReadResult(postings)


# ---- Oracle Cloud recruiting --------------------------------------------------------------------------------------

ORACLE_PAGE = 100
ORACLE_MAX_JOBS = 2500


def parse_oracle(data: Any, host: str, site: str) -> tuple[list[PostingIn], int | None]:
    """Oracle's candidate-experience list: {"items": [{"TotalJobsCount", "requisitionList": [{Id, Title, PostedDate, PrimaryLocation, WorkplaceType}]}]}."""
    items = data.get("items") if isinstance(data, dict) else None
    head = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
    total = head.get("TotalJobsCount") if isinstance(head.get("TotalJobsCount"), int) else None
    out: list[PostingIn] = []
    for j in head.get("requisitionList") or []:
        if not isinstance(j, dict) or j.get("Id") is None or not j.get("Title"):
            continue
        loc = j.get("PrimaryLocation") if isinstance(j.get("PrimaryLocation"), str) and j["PrimaryLocation"].strip() else None
        if loc:
            loc = re.sub(r",\s*United States$", "", loc)
        title = str(j["Title"]).strip()
        out.append(
            PostingIn(
                ext_id=str(j["Id"]), title=title, url=f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{j['Id']}",
                location=loc, work_type=work_type_from(str(j.get("WorkplaceType") or "").replace("-", "") or None, loc, title),
                posted_at=_date(j.get("PostedDate")),
            )
        )
    return out, total


async def _read_oracle(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    try:
        host, site = identifier.split("|")
    except ValueError as exc:
        raise ReaderError("that Oracle address is incomplete", gone=True) from exc
    postings: list[PostingIn] = []
    total: int | None = None
    complete = False
    offset = 0
    while offset < ORACLE_MAX_JOBS:
        # The finder is written out whole: Oracle wants its semicolon and commas as they are.
        url = (
            f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList"
            f"&finder=findReqs;siteNumber={site},limit={ORACLE_PAGE},offset={offset},sortBy=POSTING_DATES_DESC"
        )
        data = await _request(client, throttle, "oracle", "GET", url)
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ReaderError("the site's answer was not what we expected")
        page, count = parse_oracle(data, host, site)
        total = count if count is not None else total
        postings.extend(page)
        offset += len(page)
        if not page or (total is not None and offset >= total):
            complete = True
            break
    notes = [] if complete else [f"read the first {len(postings)} of {total or 'many'} jobs"]
    return ReadResult(postings, complete=complete, notes=notes)


# ---- iCIMS (page reading) -----------------------------------------------------------------------------------------

ICIMS_MAX_PAGES = 40


def _icims_place(raw: str) -> str | None:
    """iCIMS writes places like "US-MA-Waltham", "US-Remote" or "GB-London"; several are joined with " | " or ";"."""
    out: list[str] = []
    for chunk in re.split(r"\s*[|;]\s*", raw.strip()):
        parts = [p.strip() for p in chunk.split("-")]
        if len(parts) >= 2 and re.fullmatch(r"[A-Za-z]{2}", parts[0]):
            country, rest = parts[0].upper(), parts[1:]
            if len(rest) == 1:
                place = "Remote" if rest[0].lower() == "remote" else rest[0]
            elif country == "US":
                place = f"{'-'.join(rest[1:])}, {rest[0]}"
            else:
                place = f"{'-'.join(rest[1:])}, {country}"
        else:
            place = chunk.strip()
        if place and place not in out:
            out.append(place)
    return "; ".join(out) or None


def parse_icims(page: Any, host: str) -> tuple[list[PostingIn], int | None]:
    """iCIMS' search page (https://<name>.icims.com/jobs/search?ss=1&in_iframe=1): one <li class="iCIMS_JobCardItem"> per opening, and "Page 1 of N"."""
    import html as _html

    html = page if isinstance(page, str) else ""
    pages_m = re.search(r"Page\s+\d+\s+of\s+(\d+)", html)
    pages = int(pages_m.group(1)) if pages_m else None
    out: list[PostingIn] = []
    seen: set[str] = set()
    for block in re.split(r'<li[^>]*class="[^"]*iCIMS_JobCardItem', html)[1:]:
        link = re.search(r'href="(https?://[^"]*?/jobs/(\d+)/[^"?]*)(?:\?[^"]*)?"', block)
        if not link or link.group(2) in seen:
            continue
        title_m = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        title = _plain(title_m.group(1)) if title_m else ""
        if not title:
            attr = re.search(r'title="\d+\s*-\s*([^"]+)"', block)
            title = _html.unescape(attr.group(1)).strip() if attr else ""
        if not title:
            continue
        seen.add(link.group(2))
        loc_m = re.search(r"Job Locations</span>\s*<span[^>]*>(.*?)</span>", block, re.S)
        loc = _icims_place(_plain(loc_m.group(1))) if loc_m else None
        out.append(PostingIn(ext_id=link.group(2), title=title, url=link.group(1), location=loc, work_type=work_type_from(None, loc, title)))
    return out, pages


async def _read_icims(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    postings: list[PostingIn] = []
    pages: int | None = None
    complete = False
    for n in range(ICIMS_MAX_PAGES):
        page = await _request(client, throttle, "icims", "GET", f"https://{identifier}/jobs/search?ss=1&in_iframe=1&pr={n}", text=True, headers={"Accept": "text/html"})
        found, count = parse_icims(page, identifier)
        if n == 0:
            pages = count
            if not found and not _NO_JOBS.search(_plain(page)):
                raise ReaderError("we couldn't make sense of that careers page")
        postings.extend(p for p in found if p.ext_id not in {q.ext_id for q in postings})
        if not found or n + 1 >= (pages or 1):
            complete = True
            break
    notes = [] if complete else [f"read the first {len(postings)} jobs"]
    return ReadResult(postings, complete=complete, notes=notes)


# ---- Taleo (page reading) -----------------------------------------------------------------------------------------

def parse_taleo(page: Any) -> list[PostingIn]:
    """Taleo's career-site list (.../ats/careers/v2/searchResults?org=..&cws=..): each opening is a title link to viewRequisition?rid=<n> followed by its place."""
    import html as _html

    html = page if isinstance(page, str) else ""
    out: list[PostingIn] = []
    seen: set[str] = set()
    for m in re.finditer(r'<h4[^>]*head-title[^>]*>\s*<a[^>]+href="([^"]*rid=(\d+)[^"]*)"[^>]*>(.*?)</a>\s*</h4>\s*(?:<div[^>]*>(.*?)</div>)?', html, re.S):
        rid, title = m.group(2), _plain(m.group(3))
        if rid in seen or not title:
            continue
        seen.add(rid)
        loc = _plain(m.group(4) or "") or None
        out.append(PostingIn(ext_id=rid, title=title, url=_html.unescape(m.group(1)), location=loc, work_type=work_type_from(None, loc, title)))
    return out


async def _read_taleo(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    try:
        host, inst, org, cws = identifier.split("|")
    except ValueError as exc:
        raise ReaderError("that Taleo address is incomplete", gone=True) from exc
    page = await _request(client, throttle, "taleo", "GET", f"https://{host}/{inst}/ats/careers/v2/searchResults?org={org}&cws={cws}", text=True, headers={"Accept": "text/html"})
    postings = parse_taleo(page)
    if not postings and not _NO_JOBS.search(_plain(page)):
        raise ReaderError("we couldn't make sense of that careers page")
    more = bool(re.search(r"(?i)next\s*page|pagination", page)) and len(postings) >= 25
    return ReadResult(postings, complete=not more, notes=[f"read the first {len(postings)} jobs"] if more else [])


# ---- Phenom (job list answer) -------------------------------------------------------------------------------------

def parse_phenom(data: Any) -> tuple[list[PostingIn], int | None]:
    """Phenom's search answer: {"refineSearch": {"totalHits": n, "data": {"jobs": [{title, jobId, location, postedDate, applyUrl}]}}}."""
    import html as _html

    block = data.get("refineSearch") if isinstance(data, dict) else None
    total = block.get("totalHits") if isinstance(block, dict) and isinstance(block.get("totalHits"), int) else None
    jobs = ((block or {}).get("data") or {}).get("jobs") if isinstance(block, dict) else None
    out: list[PostingIn] = []
    for j in jobs or []:
        if not isinstance(j, dict) or not j.get("title") or not (j.get("jobId") or j.get("reqId")):
            continue
        loc = j.get("location") if isinstance(j.get("location"), str) and j["location"].strip() else None
        title = str(j["title"]).strip()
        code = str(j.get("jobId") or j.get("reqId"))
        url = _html.unescape(str(j.get("applyUrl") or ""))
        if not url.startswith("http"):
            continue
        out.append(PostingIn(ext_id=code, title=title, url=url, location=loc, work_type=work_type_from(None, loc, title), posted_at=_date(j.get("postedDate"))))
    return out, total


async def _read_phenom(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    postings: list[PostingIn] = []
    total: int | None = None
    complete = False
    start = 0
    while start < PHENOM_MAX_JOBS:
        body = {
            "lang": "en_global", "deviceType": "desktop", "country": "global", "pageName": "search-results", "ddoKey": "refineSearch",
            "sortBy": "", "subsearch": "", "from": start, "jobs": True, "counts": True, "all_fields": ["category", "country", "state", "city", "type"],
            "size": PHENOM_PAGE, "clearAll": False, "jdsource": "facets", "isSliderEnable": False, "pageId": "page14", "siteType": "external",
            "keywords": "", "global": True, "selected_fields": {}, "sort": {"order": "desc", "field": "postedDate"}, "locationData": {},
        }
        data = await _request(client, throttle, "phenom", "POST", f"https://{identifier}/widgets", json=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
        if not isinstance(data, dict) or not isinstance(data.get("refineSearch"), dict):
            raise ReaderError("the site's answer was not what we expected")
        page, count = parse_phenom(data)
        total = count if count is not None else total
        postings.extend(p for p in page if p.ext_id not in {q.ext_id for q in postings[-PHENOM_PAGE * 2:]})
        start += PHENOM_PAGE
        if len(page) == 0 or (total is not None and start >= total):
            complete = True
            break
    notes = [] if complete else [f"read the first {len(postings)} of {total or 'many'} jobs"]
    return ReadResult(postings, complete=complete, notes=notes)


# ---- SAP SuccessFactors career sites (page reading) ---------------------------------------------------------------

def parse_successfactors(page: Any, host: str) -> tuple[list[PostingIn], int | None]:
    """A SuccessFactors search page (https://<host>/<site>/search/): rows of tr.data-row with a jobTitle-link and a place, and "Results 1 to 25 of N"."""
    import html as _html

    html = page if isinstance(page, str) else ""
    total_m = re.search(r"Results\s+\d+\s+\S+\s+\d+\s+of\s+([\d,]+)", html)
    total = int(total_m.group(1).replace(",", "")) if total_m else None
    out: list[PostingIn] = []
    seen: set[str] = set()
    for block in re.split(r'<tr[^>]*class="[^"]*data-row', html)[1:]:
        link = re.search(r'<a[^>]+href="(/[^"]*?/job/[^"]*?/(\d+)/?)"[^>]*class="jobTitle-link"[^>]*>(.*?)</a>', block, re.S) or re.search(
            r'<a[^>]+class="jobTitle-link"[^>]+href="(/[^"]*?/job/[^"]*?/(\d+)/?)"[^>]*>(.*?)</a>', block, re.S)
        if not link or link.group(2) in seen:
            continue
        title = _plain(link.group(3))
        if not title:
            continue
        seen.add(link.group(2))
        loc_m = re.search(r'class="[^"]*colLocation[^"]*"[^>]*>(.*?)</td>', block, re.S)
        loc = _plain(loc_m.group(1)) if loc_m else None
        if not loc:
            st = re.search(r'class="jobState[^"]*"[^>]*>(.*?)</span>', block, re.S)
            loc = _plain(st.group(1)) if st else None
        if loc:
            loc = re.sub(r"\s*\+\d+ more\S*", "", loc)  # "+73 more..." when a job lists many places
            loc = re.sub(r",\s*\d{5}(?:-\d{4})?\b", "", loc)
            loc = re.sub(r",\s*US\b", "", loc).strip(" ,") or None
        date_m = re.search(r'class="[^"]*colDate[^"]*"[^>]*>(.*?)</td>', block, re.S)
        posted = _sf_date(_plain(date_m.group(1))) if date_m else None
        out.append(
            PostingIn(ext_id=link.group(2), title=title, url=f"https://{host}{_html.unescape(link.group(1))}", location=loc or None,
                      work_type=work_type_from(None, loc, title), posted_at=posted)
        )
    return out, total


def _sf_date(text: str) -> dt.date | None:
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%y", "%m/%d/%Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            day = dt.datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
        return day if day <= dt.date.today() else None
    return None


async def _read_successfactors(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    try:
        host, site = identifier.split("|")
    except ValueError as exc:
        raise ReaderError("that careers address is incomplete", gone=True) from exc
    country = SUCCESSFACTORS_COUNTRY.get(host)
    postings: list[PostingIn] = []
    total: int | None = None
    complete = False
    row = 0
    while row < SUCCESSFACTORS_MAX_JOBS:
        facet = f"&optionsFacetsDD_country={country}" if country else ""
        page = await _request(client, throttle, "successfactors", "GET", f"https://{host}/{site}/search/?q={facet}&startrow={row}", text=True, headers={"Accept": "text/html"})
        found, count = parse_successfactors(page, host)
        if row == 0 and not found and not _NO_JOBS.search(_plain(page)):
            raise ReaderError("we couldn't make sense of that careers page")
        total = count if count is not None else total
        postings.extend(p for p in found if p.ext_id not in {q.ext_id for q in postings[-SUCCESSFACTORS_PAGE * 2:]})
        row += SUCCESSFACTORS_PAGE
        if not found or (total is not None and row >= total):
            complete = True
            break
    notes = [] if complete else [f"read the first {len(postings)} of {total or 'many'} jobs"]
    return ReadResult(postings, complete=complete, notes=notes)


# ---- Dayforce (job list answer, needs the site's own security token first) ----------------------------------------

DAYFORCE_MAX_JOBS = 3000


def parse_dayforce(data: Any, ns: str, board: str, culture: str) -> tuple[list[PostingIn], int | None]:
    """Dayforce's search answer: {"jobPostings": [{jobPostingId, jobTitle, postingStartTimestampUTC, hasVirtualLocation, postingLocations}], "maxCount": n}."""
    total = data.get("maxCount") if isinstance(data, dict) and isinstance(data.get("maxCount"), int) else None
    out: list[PostingIn] = []
    for j in (data.get("jobPostings") if isinstance(data, dict) else None) or []:
        if not isinstance(j, dict) or j.get("jobPostingId") is None or not j.get("jobTitle"):
            continue
        title = re.sub(r"^\d{3,}\s*-\s*", "", str(j["jobTitle"]).strip()) or str(j["jobTitle"]).strip()  # the title starts with an internal job number
        places: list[str] = []
        for loc in j.get("postingLocations") or []:
            if not isinstance(loc, dict):
                continue
            city, state = str(loc.get("city") or "").strip(), str(loc.get("stateCode") or "").strip()
            text = ", ".join(x for x in (city, state) if x) or str(loc.get("formattedAddress") or "").strip()
            if text and text not in places:
                places.append(text)
        has_city = any("," in p for p in places)
        if not places and j.get("hasVirtualLocation") is True:
            places = ["Remote"]
        loc_text = "; ".join(places) or None
        declared = "remote" if j.get("hasVirtualLocation") is True and not has_city else None
        out.append(
            PostingIn(
                ext_id=str(j["jobPostingId"]), title=title, url=f"https://jobs.dayforcehcm.com/{culture}/{ns}/{board}/jobs/{j['jobPostingId']}",
                location=loc_text, work_type=work_type_from(declared, loc_text, title), posted_at=_date(j.get("postingStartTimestampUTC")),
            )
        )
    return out, total


async def _read_dayforce(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    try:
        ns, board, culture = identifier.split("|")
    except ValueError as exc:
        raise ReaderError("that Dayforce address is incomplete", gone=True) from exc
    base = "https://jobs.dayforcehcm.com"
    token = await _request(client, throttle, "dayforce", "GET", f"{base}/api/auth/csrf")  # the site hands out a token and a cookie, as it does to any visitor
    csrf = token.get("csrfToken") if isinstance(token, dict) else None
    if not isinstance(csrf, str) or not csrf:
        raise ReaderError("the site's answer was not what we expected")
    headers = {"Content-Type": "application/json", "Accept": "application/json", "x-csrf-token": csrf, "Origin": base, "Referer": f"{base}/{culture}/{ns}/{board}"}
    postings: list[PostingIn] = []
    total: int | None = None
    complete = False
    start = 0
    while start < DAYFORCE_MAX_JOBS:
        body = {"clientNamespace": ns, "jobBoardCode": board, "cultureCode": culture, "distanceUnit": 0, "paginationStart": start}
        data = await _request(client, throttle, "dayforce", "POST", f"{base}/api/geo/{ns}/jobposting/search", json=body, headers=headers)
        if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
            raise ReaderError("the site's answer was not what we expected")
        page, count = parse_dayforce(data, ns, board, culture)
        total = count if count is not None else total
        postings.extend(p for p in page if p.ext_id not in {q.ext_id for q in postings})
        start += len(data["jobPostings"])
        if not data["jobPostings"] or (total is not None and start >= total):
            complete = True
            break
    notes = [] if complete else [f"read the first {len(postings)} of {total or 'many'} jobs"]
    return ReadResult(postings, complete=complete, notes=notes)


# ---- KPMG US careers site (page reading) --------------------------------------------------------------------------

KPMG_MAX_PAGES = 120
_KPMG_HOST = "www.kpmguscareers.com"


def parse_kpmg(page: Any) -> list[PostingIn]:
    """KPMG's job search page (https://www.kpmguscareers.com/job-search/?spage=N): 12 cards, each with a link to /jobdetail/?jobId=<n>, a title and "Group | Place; Place"."""
    out: list[PostingIn] = []
    seen: set[str] = set()
    for block in re.split(r'<div class="search--item', page if isinstance(page, str) else "")[1:]:
        link = re.search(r'href="(/jobdetail/\?jobId=(\d+))"', block)
        if not link or link.group(2) in seen:
            continue
        lv = block[block.find("list-view"):] if "list-view" in block else block
        title_m = re.search(r'<div class="h5[^"]*">(.*?)</div>', lv, re.S)
        title = _plain(title_m.group(1)) if title_m else ""
        if not title:
            continue
        seen.add(link.group(2))
        meta_m = re.search(r'<div class="text-xs[^"]*">(.*?)</div>', lv, re.S)
        meta = _plain(meta_m.group(1)) if meta_m else ""
        loc = meta.split("|", 1)[1].strip() if "|" in meta else None
        out.append(PostingIn(ext_id=link.group(2), title=title, url=f"https://{_KPMG_HOST}{link.group(1)}", location=loc or None, work_type=work_type_from(None, loc, title)))
    return out


async def _read_kpmg(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    postings: list[PostingIn] = []
    complete = False
    for n in range(1, KPMG_MAX_PAGES + 1):
        url = f"https://{_KPMG_HOST}/job-search/" + (f"?spage={n}" if n > 1 else "")
        page = await _request(client, throttle, "kpmg", "GET", url, text=True, headers={"Accept": "text/html"})
        found = parse_kpmg(page)
        if n == 1 and not found:
            raise ReaderError("we couldn't make sense of that careers page")
        new = [p for p in found if p.ext_id not in {q.ext_id for q in postings}]
        postings.extend(new)
        if not new:
            complete = True
            break
    notes = [] if complete else [f"read the first {len(postings)} jobs"]
    return ReadResult(postings, complete=complete, notes=notes)


# ---- Deloitte US careers site (page reading) ----------------------------------------------------------------------

DELOITTE_MAX_PAGES = 300  # 10 jobs a page
_DELOITTE_HOST = "apply.deloitte.com"


def parse_deloitte(page: Any) -> list[PostingIn]:
    """Deloitte's job search page (https://apply.deloitte.com/en_US/careers/SearchJobs?jobOffset=N): 10 result cards, each a
    link to /JobDetail/<slug>/<id>, then "Deloitte US | Business | Place"."""
    out: list[PostingIn] = []
    seen: set[str] = set()
    for block in re.split(r'<article class="article--result', page if isinstance(page, str) else "")[1:]:
        block = block.split("</article>", 1)[0]
        link = re.search(r'href="(https://apply\.deloitte\.com/en_US/careers/JobDetail/[^"]*?/(\d+))"', block)
        if not link or link.group(2) in seen:
            continue
        title_m = re.search(r'<a[^>]+class="link"[^>]*>(.*?)</a>', block, re.S)
        title = _plain(title_m.group(1)) if title_m else ""
        if not title:
            continue
        seen.add(link.group(2))
        sub_m = re.search(r'article__header__text__subtitle">(.*?)</div>', block, re.S)
        spans = [_plain(x) for x in re.findall(r"<span[^>]*>(.*?)</span>", sub_m.group(1), re.S)] if sub_m else []
        spans = [x for x in spans if x]
        loc = spans[-1] if len(spans) >= 3 else None
        out.append(PostingIn(ext_id=link.group(2), title=title, url=link.group(1), location=loc, work_type=work_type_from(None, loc, title)))
    return out


async def _read_deloitte(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    postings: list[PostingIn] = []
    seen: set[str] = set()
    complete = False
    for n in range(DELOITTE_MAX_PAGES):
        url = f"https://{_DELOITTE_HOST}/en_US/careers/SearchJobs" + (f"?jobOffset={n * 10}" if n else "")
        page = await _request(client, throttle, "deloitte", "GET", url, text=True, headers={"Accept": "text/html"})
        found = parse_deloitte(page)
        if n == 0 and not found:
            raise ReaderError("we couldn't make sense of that careers page")
        new = [p for p in found if p.ext_id not in seen]
        seen.update(p.ext_id for p in new)
        postings.extend(new)
        if not new:
            complete = True
            break
    notes = [] if complete else [f"read the first {len(postings)} jobs"]
    return ReadResult(postings, complete=complete, notes=notes)


# ---- TalentBrew / Radancy career sites (page reading) ---------------------------------------------------------------

TALENTBREW_PAGE = 20
TALENTBREW_MAX_PAGES = 400
_TB_QUERY = (
    "ActiveFacetID=0&CurrentPage={page}&RecordsPerPage=20&TotalContentResults=&Distance=50&RadiusUnitType=0&Keywords=&Location="
    "&Latitude=&Longitude=&ShowRadius=False&IsPagination={pag}&CustomFacetName=&FacetTerm=&FacetType=0"
    "&SearchResultsModuleName=Search+Results&SearchFiltersModuleName=Search+Filters&SortCriteria=0&SortDirection=0&SearchType=5"
    "&PostalCode=&ResultsType=0&fc=&fl=&fcf=&afc=&afl=&afcf=&TotalContentPages=NaN"
)


def parse_talentbrew(data: Any, host: str) -> tuple[list[PostingIn], int | None]:
    """A TalentBrew list answer ({"results": "<html>"} from /search-jobs/results): each opening is <a href="/job/<city>/<slug>/<org>/<id>">
    with the title in an <h2>, then "job-location" and "job-worksetting" spans. Returns (postings, total jobs)."""
    html = data.get("results") if isinstance(data, dict) else None
    if not isinstance(html, str):
        return [], None
    total_m = re.search(r'data-total-job-results="(\d+)"', html)
    out: list[PostingIn] = []
    seen: set[str] = set()
    for m in re.finditer(r'<li>\s*<a href="(/job/[^"]+/(\d+))"[^>]*>(.*?)</a>', html, re.S):
        jid = m.group(2)
        body = m.group(3)
        title_m = re.search(r"<h2[^>]*>(.*?)</h2>", body, re.S)
        title = _plain(title_m.group(1)) if title_m else ""
        if not title or jid in seen:
            continue
        seen.add(jid)
        places = [_plain(x) for x in re.findall(r'<span class="job-location[^"]*">(.*?)</span>', body, re.S)]
        places = [x for x in places if x]
        loc = "; ".join(places) or None
        ws_m = re.search(r'<span class="job-info job-worksetting">(.*?)</span>', body, re.S)
        declared = _plain(ws_m.group(1)) if ws_m else None
        out.append(PostingIn(ext_id=jid, title=title, url=f"https://{host}{m.group(1)}", location=loc, work_type=work_type_from(declared, loc, title)))
    return out, int(total_m.group(1)) if total_m else None


async def _read_talentbrew(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    host = identifier.strip().lower()
    if host not in TALENTBREW_SITES:
        raise ReaderError("that careers site isn't one we read yet", gone=True)
    postings: list[PostingIn] = []
    seen: set[str] = set()
    complete = False
    for n in range(1, TALENTBREW_MAX_PAGES + 1):
        # IsPagination=True asks for the job list only; the first answer carries a very large filter list we do not need.
        url = f"https://{host}/search-jobs/results?" + _TB_QUERY.format(page=n, pag="True" if n > 1 else "False")
        data = await _request(client, throttle, "talentbrew", "GET", url, headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
        found, total = parse_talentbrew(data, host)
        if n == 1 and not found:
            if isinstance(data, dict) and data.get("hasJobs") is False:
                return ReadResult([], complete=True)
            raise ReaderError("we couldn't make sense of that careers page")
        new = [p for p in found if p.ext_id not in seen]
        seen.update(p.ext_id for p in new)
        postings.extend(new)
        if not new or len(found) < TALENTBREW_PAGE or (total is not None and len(postings) >= total):
            complete = True
            break
    notes = [] if complete else [f"read the first {len(postings)} jobs"]
    return ReadResult(postings, complete=complete, notes=notes)


# ---- Jibe career sites (public job list) ----------------------------------------------------------------------------

JIBE_PAGE = 100
JIBE_MAX_PAGES = 100


def parse_jibe(data: Any, host: str) -> tuple[list[PostingIn], int | None]:
    """A Jibe list answer (https://<site>/api/jobs?page=N&limit=M): {"jobs": [{"data": {slug, title, city, state, country, country_code,
    posted_date, description, tags2 (pay text) ...}}], "totalCount": n}. Returns (postings, total jobs)."""
    if not isinstance(data, dict):
        return [], None
    total = data.get("totalCount")
    out: list[PostingIn] = []
    seen: set[str] = set()
    for item in data.get("jobs") or []:
        d = item.get("data") if isinstance(item, dict) else None
        if not isinstance(d, dict):
            continue
        jid = str(d.get("slug") or d.get("req_id") or "").strip()
        title = str(d.get("title") or "").strip()
        if not jid or not title or jid in seen:
            continue
        seen.add(jid)
        city, state, country = (str(d.get(k) or "").strip() for k in ("city", "state", "country"))
        code = str(d.get("country_code") or "").upper()
        if code == "US":
            loc = ", ".join(x for x in (city, state) if x) or "United States"
            loc = f"{loc}, United States" if state or city else loc
        else:
            loc = ", ".join(x for x in (city, country) if x) or str(d.get("full_location") or "").strip() or None
        body = html_to_text(str(d.get("description") or ""))
        # the pay range is kept as text in two tags ("USD $157,850.00/Yr." = low, then high); only US dollar ranges are used
        tags = [str(x) for k in ("tags2", "tags3") for x in (d.get(k) or []) if isinstance(x, str) and "USD" in x]
        nums = [float(m.replace(",", "")) for t in tags for m in re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", t)]
        pay_text = mid = None
        if nums and min(nums) >= 1000:
            lo, hi = min(nums), max(nums)
            pay_text = f"${lo:,.0f} - ${hi:,.0f} / year" if hi > lo else f"${lo:,.0f} / year"
            mid = (lo + hi) / 2
        if pay_text is None and code == "US":
            pay_text, mid = pay_from_text(body)
        out.append(PostingIn(
            ext_id=jid, title=title, url=f"https://{host}/careers-home/jobs/{jid}?lang=en-us", location=loc or None,
            work_type=work_type_from(None, loc, title), pay_text=pay_text, pay_mid=mid, posted_at=_date(d.get("posted_date")),
            description=body.strip() or None,
        ))
    return out, total if isinstance(total, int) else None


async def _read_jibe(identifier: str, client: httpx.AsyncClient, throttle: Throttle) -> ReadResult:
    host = identifier.strip().lower()
    if host not in JIBE_SITES:
        raise ReaderError("that careers site isn't one we read yet", gone=True)
    postings: list[PostingIn] = []
    seen: set[str] = set()
    complete = False
    for n in range(1, JIBE_MAX_PAGES + 1):
        data = await _request(client, throttle, "jibe", "GET", f"https://{host}/api/jobs?page={n}&limit={JIBE_PAGE}", headers={"Accept": "application/json"})
        found, total = parse_jibe(data, host)
        if n == 1 and not found:
            if isinstance(data, dict) and total == 0:
                return ReadResult([], complete=True)
            raise ReaderError("we couldn't make sense of that careers page")
        new = [p for p in found if p.ext_id not in seen]
        seen.update(p.ext_id for p in new)
        postings.extend(new)
        if not new or (total is not None and len(postings) >= total):
            complete = True
            break
    notes = [] if complete else [f"read the first {len(postings)} jobs"]
    return ReadResult(postings, complete=complete, notes=notes)


# ---- entry point --------------------------------------------------------------------------------------------------

_READERS = {"greenhouse": _read_greenhouse, "lever": _read_lever, "ashby": _read_ashby, "workday": _read_workday, "smartrecruiters": _read_smartrecruiters,
    "breezy": _read_breezy, "workable": _read_workable, "bamboohr": _read_bamboohr, "pinpoint": _read_pinpoint,
    "jazzhr": _read_jazzhr, "jobvite": _read_jobvite, "oracle": _read_oracle, "icims": _read_icims,
    "taleo": _read_taleo, "phenom": _read_phenom, "successfactors": _read_successfactors,
    "dayforce": _read_dayforce, "kpmg": _read_kpmg, "deloitte": _read_deloitte, "talentbrew": _read_talentbrew, "jibe": _read_jibe,
}


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
