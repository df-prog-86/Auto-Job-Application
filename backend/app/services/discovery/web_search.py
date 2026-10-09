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
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.schemas.job_search import JobSearchIn
from app.services.discovery.normalization import parse_posted_date, strip_tracking_params
from app.services.discovery import ats
from app.services.llm.client import LLMClient
from app.services.llm.exceptions import LLMNotConfiguredError

log = logging.getLogger("job_search")

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
        if item.get("ats_checked"):
            return None  # the posting's own system already answered
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
        "builtincolorado.com", "digitalhire.com", "diversityjobs.com", "careerjet.com", "jora.com", "jobsora.com",
        "whatjobs.com", "recruit.net", "ihirehealthcare.com", "healthecareers.com", "jobtarget.com",
        "diversityworking.com", "mediabistro.com", "ladders.com", "nexxt.com", "jobserve.com", "salary.com",
    }
)
MAX_RESOLVE = 8  # job-board results looked up per search, to keep the cost and wait predictable


def is_aggregator(url: str) -> bool:
    """True when the link is on a job board or aggregator rather than the employer's own site."""
    host = (urlsplit(url.strip()).hostname or "").lower().removeprefix("www.")
    return any(host == d or host.endswith(f".{d}") for d in AGGREGATOR_DOMAINS)


# Hosts of real applicant-tracking and careers systems; a link here is the employer's own posting.
_ATS_SUFFIXES = (
    "myworkdayjobs.com", "greenhouse.io", "ashbyhq.com", "lever.co", "icims.com", "smartrecruiters.com", "taleo.net",
    "oraclecloud.com", "successfactors.com", "successfactors.eu", "jobvite.com", "bamboohr.com", "paylocity.com",
    "ultipro.com", "workable.com", "breezy.hr", "recruitee.com", "applytojob.com", "teamtailor.com", "pinpointhq.com",
    "dayforcehcm.com", "paycomonline.net", "rippling.com", "myworkdaysite.com", "adp.com", "brassring.com", "avature.net",
    "phenom.com", "eightfold.ai", "csod.com", "peopleadmin.com", "governmentjobs.com",
)
_BOARD_WORDS = re.compile(r"job|career|hire|hiring|recruit|talent|staff|employ|diversity|vacanc|opening", re.I)
_COMPANY_STOP = {"the", "inc", "llc", "ltd", "corp", "co", "company", "group", "and"}


def _registrable(host: str) -> str:
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "gov", "ac") and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


# Venture-capital and community job boards (Getro, Consider and similar) list many companies' jobs under /companies/<name>/jobs/.
_PORTFOLIO_BOARD_PATH = re.compile(r"^/(companies|company|orgs?)/[^/]+/(jobs?|positions?|openings?)(/|$)", re.I)


def is_board_url(url: str, company: str | None) -> bool:
    """
    True when the link is on a job board or a similar middleman. Known boards are listed; unknown ones are caught by their look:
    a site that is not an applicant-tracking system, does not carry the employer's name, and is itself named like a jobs site.
    """
    if is_aggregator(url):
        return True
    host = (urlsplit(url.strip()).hostname or "").lower().removeprefix("www.")
    if any(host == d or host.endswith(f".{d}") for d in _ATS_SUFFIXES):
        return False
    if _PORTFOLIO_BOARD_PATH.match(urlsplit(url.strip()).path):
        return True  # a middleman's page about one company's job, not the company's own site
    base = _registrable(host)
    squashed = re.sub(r"[^a-z0-9]", "", base.split(".")[0])
    words = [w for w in re.findall(r"[a-z0-9]+", (company or "").lower()) if w not in _COMPANY_STOP]
    if words and (words[0] in squashed or "".join(words[:2]) in squashed or squashed in "".join(words)):
        return False  # carries the employer's own name
    return bool(_BOARD_WORDS.search(squashed))


def is_board_result(item: dict[str, Any]) -> bool:
    return is_board_url(item["url"], item.get("company"))


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
    if not is_http_url(url) or not is_public_host(url) or is_board_url(url, item.get("company")):
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
    todo = [i for i in items if is_board_result(i)]
    if not todo:
        return items, 0
    model = search_model()
    gate = asyncio.Semaphore(3)

    async def one(item: dict[str, Any]) -> dict[str, Any] | None:
        async with gate:
            try:
                result = await LLMClient().chat_completion(
                    model=model,
                    messages=build_resolve_messages(item),
                    temperature=0.0,
                    max_tokens=400,
                    extra={"plugins": [web_plugin(5)]},
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
        if is_board_result(item):
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


async def enrich_from_ats(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """
    Asks Workday, Greenhouse, Ashby and Lever themselves whether each posting is open and when it was published.
    Clearly closed ones are removed; the date fills in when the search did not give one.
    """
    gate = asyncio.Semaphore(6)
    boards: dict[str, tuple[int, Any]] = {}
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:

        async def one(item: dict[str, Any]) -> None:
            async with gate:
                info = await ats.inspect(item["url"], client, boards)
            if not info.checked:
                return
            item["ats_checked"] = True
            item["ats_live"] = info.live
            if info.posted and not item.get("posted_at"):
                item["posted_at"] = info.posted
            if info.pay and not item.get("salary_text"):
                item["salary_text"] = info.pay

        await asyncio.gather(*(one(i) for i in items))
    kept = [i for i in items if i.get("ats_live") is not False]
    return kept, len(items) - len(kept)


def apply_pay_rules(items: list[dict[str, Any]], criteria: JobSearchIn) -> tuple[list[dict[str, Any]], int]:
    """Pay filters, applied once pay has been read from the postings themselves."""
    kept = []
    for item in items:
        if criteria.require_salary and not item.get("salary_text"):
            continue
        if criteria.target_salary and item.get("salary_text"):
            mid = salary_midpoint(item["salary_text"])
            if mid is not None and mid < salary_floor(criteria.target_salary):
                continue
        kept.append(item)
    return kept, len(items) - len(kept)


async def fill_posted_dates(
    items: list[dict[str, Any]], within_days: int, need_pay: bool = False
) -> tuple[list[dict[str, Any]], int]:
    """
    Results the AI gave no date for get one from the posting page itself. When a date window was asked for,
    postings that are clearly older are dropped. Still no date means it is kept, and shown as "date not listed".
    """
    gate = asyncio.Semaphore(5)

    async def one(item: dict[str, Any]) -> None:
        needs_date = not item.get("posted_at") and not item.get("ats_checked")
        needs_pay = need_pay and not item.get("salary_text") and not item.get("ats_checked")
        if not (needs_date or needs_pay) or not is_public_host(item["url"]):
            return
        async with gate:
            try:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, max_redirects=5) as client:
                    resp = await client.get(item["url"], headers={"User-Agent": _UA, "Accept": "text/html,*/*"})
                    if resp.status_code == 200:
                        page = resp.text[:600000]
                        if needs_date:
                            item["posted_at"] = extract_posted_date(page)
                        if needs_pay:
                            item["salary_text"] = ats.extract_pay_text(page)
            except Exception:
                return

    await asyncio.gather(*(one(i) for i in items))
    if not within_days:
        return items, 0
    kept = [i for i in items if not i.get("posted_at") or (dt.date.today() - i["posted_at"]).days <= within_days]
    return kept, len(items) - len(kept)


# The search is split by where jobs live, so each call looks at one kind of source and returns direct posting links.
WORKDAY_DOMAINS = ["*.myworkdayjobs.com"]
ATS_DOMAINS = ["boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.ashbyhq.com", "jobs.lever.co"]
SCOPES: dict[str, dict[str, Any]] = {
    "workday": {"include": WORKDAY_DOMAINS, "hint": "Search only Workday career sites."},
    "ats": {"include": ATS_DOMAINS, "hint": "Search only Greenhouse, Ashby and Lever job pages."},
    "web": {
        "exclude": sorted(AGGREGATOR_DOMAINS) + ["myworkdayjobs.com", "greenhouse.io", "ashbyhq.com", "lever.co"],
        "hint": "Search company career sites.",
    },
}


def per_call_count(criteria: JobSearchIn) -> int:
    """How many postings each source asks for: enough overlap to fill the list, without paying for the same job three times."""
    return max(3, -(-criteria.count * 6 // 10))


def build_messages(criteria: JobSearchIn, scope: str = "web") -> list[dict[str, str]]:
    wanted = [f"Role: {criteria.titles}"]
    if criteria.location:
        wanted.append(f"Location: {criteria.location}")
    if criteria.work_type != "any":
        wanted.append(f"Work type: {criteria.work_type} only")
    if criteria.keywords:
        wanted.append(f"Must relate to: {criteria.keywords}")
    if criteria.target_salary:
        floor = salary_floor(criteria.target_salary)
        wanted.append(f"Yearly pay midpoint at least ${floor:,} (no upper limit; postings with no stated pay are fine unless told otherwise)")
    if criteria.require_salary:
        wanted.append("Only postings that state their pay")
    if excluded_companies(criteria):
        wanted.append("Not from these companies: " + ", ".join(excluded_companies(criteria)))
    if criteria.posted_within_days:
        wanted.append(f"Posted within the last {criteria.posted_within_days} days")
    system = (
        "You find current job postings with web search and report them as JSON. "
        "Each url must be the page of one single job (its description and apply button), never a list of jobs, a search page, "
        "a job-alert, sign-up, resume-upload or login page, a job board or recruiter page, or a redirect link. "
        "Use the employer's own career site or applicant-tracking page only; never a job board, a niche or diversity job site, or a recruiter page. "
        "The title must be a close match for the role asked (same kind of work and level), not just share a word with it. "
        "Use only pages you found; never invent a job, company or link. "
        "Do not open pages to check if they are still open; that is checked afterwards. Skip duplicates. "
        "Return fewer items rather than weak ones; if none match, return []. "
        f"{SCOPES[scope]['hint']} "
        "Reply with ONLY a JSON array. Item keys: title, company, location (or null), work_type (remote, hybrid, onsite or unknown), "
        "salary (text from the posting or null), posted (YYYY-MM-DD only if the result shows it, else null; never guess), "
        "url, summary (one plain sentence from the posting)."
    )
    user = f"Find up to {per_call_count(criteria)} postings:\n" + "\n".join(f"- {w}" for w in wanted)
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


def _same_job_key(item: dict[str, Any]) -> str:
    squash = lambda text: re.sub(r"[^a-z0-9]+", "", (text or "").lower())
    return f"{squash(item['company'])}|{squash(item['title'])}"


def _source_rank(item: dict[str, Any]) -> int:
    """Lower is better. The applicant-tracking page is the one that can be read, scored and autofilled."""
    host = (urlsplit(item["url"]).hostname or "").lower()
    if host.endswith(("myworkdayjobs.com", "greenhouse.io", "ashbyhq.com", "lever.co")):
        return 0
    return 1 if item.get("grounded") else 2


def merge_same_jobs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same role found through two sources (an ATS page and the company site) is one result; the ATS link wins."""
    best: dict[str, dict[str, Any]] = {}
    for item in items:
        key = _same_job_key(item)
        if key not in best or _source_rank(item) < _source_rank(best[key]):
            best[key] = item
    return [i for i in items if best[_same_job_key(i)] is i]


def trim_to_count(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Keeps the best-checked results first (the employer's own system confirmed them), then the rest, up to the count asked for."""
    ranked = sorted(items, key=lambda i: (0 if i.get("ats_checked") else 1, _source_rank(i)))
    keep = {id(i) for i in ranked[:count]}
    return [i for i in items if id(i) in keep]


def _clean_items(
    raw_items: list[dict[str, Any]], criteria: JobSearchIn, grounded_keys: set[str], why: dict[str, int] | None = None
) -> list[dict[str, Any]]:
    why = why if why is not None else {}

    def skip(reason: str) -> None:
        why[reason] = why.get(reason, 0) + 1

    items: list[dict[str, Any]] = []
    excluded = excluded_companies(criteria)
    for raw_item in raw_items:
        title = _clean(raw_item.get("title"), 300)
        company = _clean(raw_item.get("company"), 300)
        link = _clean(raw_item.get("url"), 1000)
        if not title or not company or not link or not is_http_url(link):
            skip("missing title, company or link")
            continue
        link = strip_tracking_params(link)
        if is_excluded(company, excluded):
            skip("excluded company")
            continue
        if criteria.target_salary:
            mid = salary_midpoint(_clean(raw_item.get("salary"), 200))
            if mid is not None and mid < salary_floor(criteria.target_salary):
                skip("pay under your minimum")
                continue  # posted pay is clearly under the floor
        # "Only postings that state pay" is applied after the postings' own data is read: snippets rarely show pay.
        posted = parse_posted_date(_clean(raw_item.get("posted"), 40))
        if posted and criteria.posted_within_days and (dt.date.today() - posted).days > criteria.posted_within_days:
            skip("older than the date window")
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
    return items


def search_model() -> str | None:
    return settings.JOB_SEARCH_MODEL or settings.PRIMARY_FAST_MODEL


def web_plugin(max_results: int) -> dict[str, Any]:
    """The web-search settings: the engine is set explicitly so domain filters and the price do not depend on the model."""
    plugin: dict[str, Any] = {"id": "web", "engine": settings.JOB_SEARCH_ENGINE, "max_results": max_results}
    if settings.JOB_SEARCH_ENGINE_MODE:
        plugin["mode"] = settings.JOB_SEARCH_ENGINE_MODE
    return plugin


async def _search_one(criteria: JobSearchIn, scope: str, model: str) -> list[dict[str, Any]]:
    n = per_call_count(criteria)
    plugin = web_plugin(max(5, min(n + 2, 10)))
    plugin.update({k: SCOPES[scope][k] for k in ("include", "exclude") if k in SCOPES[scope]})
    if "include" in plugin:
        plugin["include_domains"] = plugin.pop("include")
    if "exclude" in plugin:
        plugin["exclude_domains"] = plugin.pop("exclude")
    result = await LLMClient().chat_completion(
        model=model,
        messages=build_messages(criteria, scope),
        temperature=0.0,
        max_tokens=2500,
        extra={"plugins": [plugin]},
        timeout=150.0,
    )
    parsed = parse_items(result.content)
    why: dict[str, int] = {}
    cleaned = _clean_items(parsed, criteria, cited_urls(result.raw), why)
    log.warning("job search [%s]: AI returned %d, %d usable; left out: %s", scope, len(parsed), len(cleaned), why or "none")
    return cleaned


async def search_jobs(criteria: JobSearchIn) -> tuple[list[dict[str, Any]], int]:
    """
    One search per kind of source (Workday, Greenhouse/Ashby/Lever, company sites), merged. Postings are then checked by code,
    not by the AI: the employer's system says whether each is open and when it was published.
    Returns the candidate postings (not yet saved) and how many were dropped as closed, too old or without an original.
    """
    model = search_model()
    if not model:
        raise LLMNotConfiguredError("No LLM provider configured (PRIMARY_FAST_MODEL unset).")
    outcomes = await asyncio.gather(*(_search_one(criteria, scope, model) for scope in SCOPES), return_exceptions=True)
    for scope, o in zip(SCOPES, outcomes):
        if isinstance(o, BaseException):
            log.warning("job search [%s]: failed: %s: %s", scope, type(o).__name__, o)
    batches = [o for o in outcomes if isinstance(o, list)]
    if not batches:
        raise next(o for o in outcomes if isinstance(o, BaseException))  # every source failed: show the first reason
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for batch in batches:
        for item in batch:
            if item["url_key"] not in seen:
                seen.add(item["url_key"])
                items.append(item)
    merged = len(items)
    items = merge_same_jobs(items)
    items, not_found = await resolve_original_sources(items)
    items, gone = await enrich_from_ats(items)
    items, too_old = await fill_posted_dates(items, criteria.posted_within_days, need_pay=criteria.require_salary)
    items, no_pay = apply_pay_rules(items, criteria)
    too_old += no_pay
    kept, closed = await drop_closed(items)
    log.warning(
        "job search: %d found across sources, %d after merging, %d dropped (no employer link %d, closed by employer %d, too old or no pay %d, closed page %d), %d left",
        merged, len(items) + not_found + gone + too_old, not_found + gone + too_old + closed, not_found, gone, too_old, closed, len(kept),
    )
    final = trim_to_count(kept, criteria.count)
    for item in final:  # working notes, not saved columns
        item.pop("ats_checked", None)
        item.pop("ats_live", None)
    return final, closed + gone + not_found + too_old
