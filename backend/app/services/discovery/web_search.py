"""
Job search across the open web, through the same LLM connection that scores and
tailors (OpenRouter's built-in web search plugin).

Nothing the model says is trusted blindly: a result needs a real http(s) link, and
links the search engine itself returned are marked "grounded". Results are only
suggestions; a job is added to the list when the person clicks Add.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.schemas.job_search import JobSearchIn
from app.services.discovery.normalization import parse_posted_date, strip_tracking_params
from app.services.llm.client import LLMClient
from app.services.llm.exceptions import LLMNotConfiguredError

WORK_TYPES = {"remote", "hybrid", "onsite"}


class JobSearchError(RuntimeError):
    """The search could not be completed; the message is safe to show."""


def url_key(url: str) -> str:
    """host + path (no scheme, query, fragment or trailing slash): two spellings of one posting match."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}".lower()


def is_http_url(url: str) -> bool:
    parts = urlsplit(url.strip())
    return parts.scheme in ("http", "https") and "." in parts.netloc


def salary_floor(target: int) -> int:
    """The lowest range midpoint to accept: the number entered, with 5% slack so near misses can be reviewed."""
    return int(target * 0.95)


_MONEY = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kK])?")


def salary_midpoint(text: str | None) -> float | None:
    """Midpoint of a yearly pay range written in the posting ("$80,000 - $100,000", "85k"). None if unclear or hourly."""
    if not text:
        return None
    values: list[float] = []
    for number, k in _MONEY.findall(text)[:2]:
        value = float(number.replace(",", ""))
        values.append(value * 1000 if k else value)
    if not values or min(values) < 1000:
        return None  # hourly or not a yearly figure: cannot tell
    return sum(values) / len(values)


def excluded_companies(criteria: JobSearchIn) -> list[str]:
    parts = re.split(r"[,;\n]", criteria.exclude_companies or "")
    return [p.strip() for p in parts if p.strip()][:20]


def is_excluded(company: str, excluded: list[str]) -> bool:
    name = company.lower()
    return any(e.lower() in name or name in e.lower() for e in excluded)


_CLOSED_PHRASES = re.compile(
    r"no longer accepting (?:applications|applicants)|is no longer (?:available|open|active|accepting)|"
    r"(?:job|position|posting|requisition|role|opening) (?:has )?(?:been )?(?:is )?(?:closed|expired|filled|removed|unavailable)|"
    r"(?:has|have) (?:been )?(?:closed|expired|filled)|"
    r"this (?:job|position|posting|requisition) (?:is )?(?:no longer|has expired|has closed|has been filled)|"
    r"job (?:was )?not found|position (?:was )?not found|we (?:could ?n.t|couldn.t) find (?:that|this|the) (?:job|page|position)|"
    r"no longer exists|not currently accepting applications",
    re.I,
)
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


def is_public_host(url: str) -> bool:
    """False for localhost and private addresses, so a search result can never aim this computer at itself."""
    host = (urlsplit(url).hostname or "").lower()
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return ip.is_global


def looks_closed(original_url: str, final_url: str, status: int, text: str) -> bool:
    """True only when the page clearly says the posting is gone. Anything unclear counts as open."""
    if status in (404, 410):
        return True
    if status != 200:
        return False
    if _CLOSED_PHRASES.search(text[:20000]):
        return True
    # Bounced to a general careers or search page instead of the posting.
    before = [p for p in urlsplit(original_url).path.split("/") if p]
    after = [p for p in urlsplit(final_url).path.split("/") if p]
    if len(before) >= 2 and len(after) <= 1:
        return True
    return len(before) >= 2 and "search" in "/".join(after).lower() and "search" not in "/".join(before).lower()


async def check_live(url: str) -> bool | None:
    """
    True = looks open, False = clearly closed or gone, None = could not tell (the site blocks
    automated visits, is slow, or builds its page with scripts). None never removes a result.
    """
    if not is_public_host(url):
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, max_redirects=5) as client:
            resp = await client.get(url, headers={"User-Agent": _UA, "Accept": "text/html,*/*"})
    except httpx.HTTPError:
        return None
    if resp.status_code in (404, 410):
        return False
    if resp.status_code != 200:
        return None
    if not is_public_host(str(resp.url)):
        return False
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", resp.text[:400000], flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return not looks_closed(url, str(resp.url), resp.status_code, re.sub(r"\s+", " ", text))


async def drop_closed(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Visits each link (a few at a time) and removes the ones that are clearly closed."""
    gate = asyncio.Semaphore(5)

    async def one(item: dict[str, Any]) -> bool | None:
        async with gate:
            return await check_live(item["url"])

    verdicts = await asyncio.gather(*(one(i) for i in items), return_exceptions=True)
    kept = [i for i, v in zip(items, verdicts) if v is not False]
    return kept, len(items) - len(kept)


# Sites that list other companies' jobs. A link here is a middleman: the real posting lives on the employer's own
# careers page or applicant-tracking page, which is where the application is filled and where it can be read.
AGGREGATOR_DOMAINS = frozenset(
    {
        "linkedin.com", "indeed.com", "ziprecruiter.com", "glassdoor.com", "monster.com", "simplyhired.com",
        "careerbuilder.com", "talent.com", "jooble.org", "adzuna.com", "dice.com", "theladders.com", "lensa.com",
        "jobrapido.com", "snagajob.com", "wellfound.com", "jobright.ai", "remoteok.com", "weworkremotely.com",
        "flexjobs.com", "learn4good.com", "jobs2careers.com", "neuvoo.com", "jobcase.com", "joblist.com",
        "jobget.com", "zippia.com", "joinhandshake.com", "simplify.jobs", "himalayas.app", "remotive.com",
        "workingnomads.com", "craigslist.org", "facebook.com", "builtin.com", "builtinnyc.com", "builtinboston.com",
        "builtinchicago.com", "builtinaustin.com", "builtinla.com", "builtinseattle.com", "builtinsf.com",
        "builtincolorado.com",
    }
)
MAX_RESOLVE = 8  # job-board results looked up per search, to keep the cost and wait predictable


def is_aggregator(url: str) -> bool:
    """True when the link is on a job board or aggregator rather than the employer's own site."""
    host = (urlsplit(url.strip()).hostname or "").lower().removeprefix("www.")
    return any(host == d or host.endswith(f".{d}") for d in AGGREGATOR_DOMAINS)


_TITLE_STOP = {"the", "and", "for", "with", "of", "to", "a", "an", "in", "at", "ii", "iii", "i", "sr", "jr", "senior", "junior"}


def _title_words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 2 and w not in _TITLE_STOP}


def parse_object(text: str) -> dict[str, Any]:
    """The first JSON object in the model's answer, tolerating code fences and a lead-in."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def build_resolve_messages(item: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "You find the original posting of a job that was found on a job board. Using web search, find the same job "
        "(same employer, same role, same location) on the employer's own careers website or its applicant-tracking "
        "page (Workday, Greenhouse, Lever, Ashby, iCIMS, SmartRecruiters, Taleo and similar). "
        "HARD REQUIREMENT: the posting must be live and accepting applications today; open the page and confirm it. "
        "The link must be the page for that one job, never a page of many jobs, a search page, a login or sign-up page, "
        "a job board, an aggregator or a recruiter page. Never guess, build or edit a link: it must come from a page you opened. "
        'Reply with ONLY a JSON object, no other text: {"url": "<link to the employer posting>"} or {"url": null} if you cannot find it.'
    )
    where = f" in {item['location']}" if item.get("location") else ""
    user = (
        f"Job: {item['title']}\nEmployer: {item['company']}{where}\n"
        f"Found on this job board page (do not return this page): {item['url']}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def _original_is_acceptable(item: dict[str, Any], url: str, grounded: bool) -> bool:
    """The found link must be a real, open, employer-side page for this job, not a lookalike."""
    if not is_http_url(url) or not is_public_host(url) or is_aggregator(url):
        return False
    if await check_live(url) is False:
        return False
    # When the page can be read, it must actually be about this job. Pages built with scripts (many Workday sites)
    # cannot be read here, so those must have been returned by the search engine itself.
    text = ""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, max_redirects=5) as client:
            resp = await client.get(url, headers={"User-Agent": _UA, "Accept": "text/html,*/*"})
        if resp.status_code == 200:
            body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", resp.text[:400000], flags=re.I | re.S)
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).lower()
    except httpx.HTTPError:
        text = ""
    if len(text) >= 500:
        words = _title_words(item["title"])
        if words and sum(1 for w in words if w in text) / len(words) < 0.5:
            return False
        return True
    return grounded


async def resolve_original_sources(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """
    For results found on job boards, looks up the same job on the employer's own site and swaps the link.
    A board result with no verified original is dropped: those links usually cannot be read, scored or filled.
    Returns the items and how many were dropped.
    """
    todo = [i for i in items if is_aggregator(i["url"])]
    if not todo:
        return items, 0
    model = settings.PRIMARY_FAST_MODEL
    gate = asyncio.Semaphore(3)

    async def one(item: dict[str, Any]) -> dict[str, Any] | None:
        async with gate:
            try:
                result = await LLMClient().chat_completion(
                    model=model,
                    messages=build_resolve_messages(item),
                    temperature=0.0,
                    max_tokens=400,
                    extra={"plugins": [{"id": "web", "max_results": 5}]},
                    timeout=90.0,
                )
            except Exception:  # a failed lookup just means no original found
                return None
            found = parse_object(result.content).get("url")
            link = _clean(found, 1000)
            if not link or not is_http_url(link):
                return None
            link = strip_tracking_params(link)
            grounded = url_key(link) in cited_urls(result.raw)
            if not await _original_is_acceptable(item, link, grounded):
                return None
            return {**item, "url": link, "url_key": url_key(link), "grounded": grounded}

    attempt = todo[:MAX_RESOLVE]
    resolved = await asyncio.gather(*(one(i) for i in attempt))
    replacement = {id(i): r for i, r in zip(attempt, resolved)}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    dropped = 0
    for item in items:
        if is_aggregator(item["url"]):
            item = replacement.get(id(item))  # type: ignore[assignment]
            if item is None:
                dropped += 1
                continue
        if item["url_key"] in seen:
            dropped += 1
            continue
        seen.add(item["url_key"])
        out.append(item)
    return out, dropped


_DATE_JSON = re.compile(r'"datePosted"\s*:\s*"(\d{4}-\d{2}-\d{2})')
_DATE_META = re.compile(
    r'<meta[^>]+(?:property|name|itemprop)=["\'](?:article:published_time|datePosted|og:published_time|date)["\'][^>]*content=["\'](\d{4}-\d{2}-\d{2})',
    re.I,
)
_DATE_AGO = re.compile(r"posted\s+(today|yesterday|(\d{1,3})\+?\s+(day|week|month)s?\s+ago)", re.I)


def extract_posted_date(html: str) -> dt.date | None:
    """The date a posting page says it was published: structured data first, then plain "Posted 3 days ago" text."""
    for pattern in (_DATE_JSON, _DATE_META):
        found = pattern.search(html)
        if found:
            day = parse_posted_date(found.group(1))
            if day:
                return day
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
    ago = _DATE_AGO.search(text)
    if not ago:
        return None
    today = dt.date.today()
    word = ago.group(1).lower()
    if word == "today":
        return today
    if word == "yesterday":
        return today - dt.timedelta(days=1)
    unit = {"day": 1, "week": 7, "month": 30}[ago.group(3).lower()]
    return today - dt.timedelta(days=int(ago.group(2)) * unit)


def workday_api_url(url: str) -> str | None:
    """
    Workday pages are built with scripts, so the page itself holds no date. Workday serves the same posting as
    data at /wday/cxs/<company>/<site>/job/<path>, which includes the start date.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host.endswith(".myworkdayjobs.com"):
        return None
    segs = [p for p in parts.path.split("/") if p]
    if segs and re.fullmatch(r"[a-z]{2}-[A-Za-z]{2}", segs[0]):
        segs = segs[1:]  # drop the language, e.g. en-US
    if "job" not in segs:
        return None
    at = segs.index("job")
    if at < 1 or at + 1 >= len(segs):
        return None
    return f"https://{host}/wday/cxs/{host.split('.')[0]}/{segs[at - 1]}/job/{'/'.join(segs[at + 1:])}"


def workday_posted_date(data: Any) -> dt.date | None:
    info = data.get("jobPostingInfo") if isinstance(data, dict) else None
    if not isinstance(info, dict):
        return None
    return parse_posted_date(info.get("startDate")) or extract_posted_date(f"Posted {info.get('postedOn', '')}")


async def fill_posted_dates(items: list[dict[str, Any]], within_days: int) -> tuple[list[dict[str, Any]], int]:
    """
    Results the AI gave no date for get one from the posting page itself. When a date window was asked for,
    postings that are clearly older are dropped. Still no date means it is kept, and shown as "date not listed".
    """
    gate = asyncio.Semaphore(5)

    async def one(item: dict[str, Any]) -> None:
        if item.get("posted_at") or not is_public_host(item["url"]):
            return
        async with gate:
            try:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, max_redirects=5) as client:
                    api = workday_api_url(item["url"])
                    if api:
                        resp = await client.get(api, headers={"User-Agent": _UA, "Accept": "application/json"})
                        if resp.status_code == 200:
                            item["posted_at"] = workday_posted_date(resp.json())
                    if not item.get("posted_at"):
                        resp = await client.get(item["url"], headers={"User-Agent": _UA, "Accept": "text/html,*/*"})
                        if resp.status_code == 200:
                            item["posted_at"] = extract_posted_date(resp.text[:600000])
            except Exception:
                return

    await asyncio.gather(*(one(i) for i in items))
    if not within_days:
        return items, 0
    kept = [i for i in items if not i.get("posted_at") or (dt.date.today() - i["posted_at"]).days <= within_days]
    return kept, len(items) - len(kept)


def build_messages(criteria: JobSearchIn) -> list[dict[str, str]]:
    wanted = [f"Job title or role: {criteria.titles}"]
    if criteria.location:
        wanted.append(f"Location: {criteria.location}")
    if criteria.work_type != "any":
        wanted.append(f"Work type: {criteria.work_type} only")
    if criteria.keywords:
        wanted.append(f"Must relate to: {criteria.keywords}")
    if criteria.target_salary:
        floor = salary_floor(criteria.target_salary)
        wanted.append(
            f"Yearly pay where the midpoint of the posted pay range is at least ${floor:,} "
            "(there is no upper limit; higher is fine; for a single posted figure use that figure; "
            "postings that state no pay may still be included unless told otherwise below)"
        )
    if criteria.require_salary:
        wanted.append("Ignore any posting that does not state its pay or pay range; every result must show pay")
    if excluded_companies(criteria):
        wanted.append("Do not include postings from these companies: " + ", ".join(excluded_companies(criteria)))
    if criteria.posted_within_days:
        wanted.append(f"Posted within the last {criteria.posted_within_days} days")
    system = (
        "You find job postings that are open right now, using web search. "
        "HARD REQUIREMENT: only recommend a job that is live and accepting applications today. "
        "Open the posting page and confirm it before including it. Exclude any posting that says it is closed, "
        "expired, filled, no longer available or no longer accepting applications, that shows no apply option, "
        "or that redirects to a general careers page or a search page. If you cannot confirm a posting is live, leave it out. "
        "LINK RULE: the url must be the actual job posting page itself, the page that shows that one job's "
        "description and where a person applies to it. Never give a pre-screening or sign-up page, a job-alert page, "
        "a resume-upload or login page, a page of many jobs or search results, an aggregator or middleman page "
        "(for example job boards, staffing or recruiter listing pages, or pages that only send people on to the real posting), "
        "or a redirect or tracking link. If a board only links to the employer's posting, follow it and give the employer's "
        "posting link instead; if you cannot find the real posting link, leave that job out. "
        "Prefer the employer's own careers page or its applicant-tracking page (Workday, Greenhouse, Lever, Ashby, iCIMS) "
        "over job-board listing pages. Skip duplicate postings. "
        "Never invent a posting, company or link: every item must come from a page you found. "
        "If you find fewer than requested, return fewer; if you find none, return an empty list. "
        "Reply with ONLY a JSON array, no other text. Each item has exactly these keys: "
        '"title", "company", "location" (or null), "work_type" ("remote", "hybrid", "onsite" or "unknown"), '
        '"salary" (text from the posting, or null), "posted" (the date the posting says it was published, as YYYY-MM-DD, or null if it does not say; never guess), '
        '"url" (direct link to that posting), '
        '"summary" (one or two plain sentences taken from the posting, no hype).'
    )
    user = f"Find up to {criteria.count} current job postings that match:\n" + "\n".join(f"- {w}" for w in wanted)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_items(text: str) -> list[dict[str, Any]]:
    """The model's answer as a list of objects. Tolerates code fences and a short lead-in."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def cited_urls(raw: dict[str, Any]) -> set[str]:
    """Keys of the links the search engine itself returned (url_citation annotations)."""
    keys: set[str] = set()
    try:
        annotations = raw["choices"][0]["message"].get("annotations") or []
    except (KeyError, IndexError, AttributeError, TypeError):
        return keys
    for a in annotations:
        if isinstance(a, dict) and a.get("type") == "url_citation":
            cite = a.get("url_citation") or {}
            if isinstance(cite, dict) and isinstance(cite.get("url"), str) and is_http_url(cite["url"]):
                keys.add(url_key(cite["url"]))
    return keys


def _clean(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text[:limit] if text else None


async def search_jobs(criteria: JobSearchIn) -> tuple[list[dict[str, Any]], int]:
    """Runs one web search; returns cleaned candidate postings (not yet saved) and how many closed ones were dropped."""
    model = settings.PRIMARY_FAST_MODEL
    if not model:
        raise LLMNotConfiguredError("No LLM provider configured (PRIMARY_FAST_MODEL unset).")
    result = await LLMClient().chat_completion(
        model=model,
        messages=build_messages(criteria),
        temperature=0.0,
        max_tokens=4000,
        extra={"plugins": [{"id": "web", "max_results": max(5, min(criteria.count, 15))}]},
        timeout=150.0,
    )
    grounded_keys = cited_urls(result.raw)
    items: list[dict[str, Any]] = []
    excluded = excluded_companies(criteria)
    for raw_item in parse_items(result.content):
        title = _clean(raw_item.get("title"), 300)
        company = _clean(raw_item.get("company"), 300)
        link = _clean(raw_item.get("url"), 1000)
        if not title or not company or not link or not is_http_url(link):
            continue
        link = strip_tracking_params(link)
        if is_excluded(company, excluded):
            continue
        if criteria.target_salary:
            mid = salary_midpoint(_clean(raw_item.get("salary"), 200))
            if mid is not None and mid < salary_floor(criteria.target_salary):
                continue  # posted pay is clearly under the floor
        if criteria.require_salary and not _clean(raw_item.get("salary"), 200):
            continue  # the person asked to see only postings that state pay
        posted = parse_posted_date(_clean(raw_item.get("posted"), 40))
        if posted and criteria.posted_within_days and (dt.date.today() - posted).days > criteria.posted_within_days:
            continue  # clearly older than the window asked for
        work_type = _clean(raw_item.get("work_type"), 30)
        work_type = work_type.lower() if work_type and work_type.lower() in WORK_TYPES else None
        items.append(
            {
                "title": title,
                "company": company,
                "location": _clean(raw_item.get("location"), 300),
                "work_type": work_type,
                "salary_text": _clean(raw_item.get("salary"), 200),
                "posted_at": posted,
                "summary": _clean(raw_item.get("summary"), 800),
                "url": link,
                "url_key": url_key(link),
                "grounded": url_key(link) in grounded_keys,
            }
        )
    items, not_found = await resolve_original_sources(items)
    items, too_old = await fill_posted_dates(items, criteria.posted_within_days)
    kept, closed = await drop_closed(items)
    return kept, closed + not_found + too_old
