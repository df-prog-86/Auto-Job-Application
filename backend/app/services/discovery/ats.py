"""
Asks an employer's applicant-tracking system directly whether a posting is still open and when it was published.

Workday, Greenhouse, Ashby and Lever all serve each posting as public data. That is more reliable than reading the page
(which is built with scripts) and costs no AI calls. Every answer is "unknown" (None) when the site does not say; unknown
never removes a result.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.services.discovery.normalization import parse_posted_date

_UA = "Mozilla/5.0 (compatible; JobAgent/1.0)"
_LANG = re.compile(r"[a-z]{2}-[A-Za-z]{2}")


_MONEY_RANGE = re.compile(
    r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s?[kK]?\s*(?:-|–|—|to)\s*\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s?[kK]?"
)


def extract_pay_text(markup: Any) -> str | None:
    """The first pay range written in a posting's text ("$120,000 - $150,000"), or None."""
    if not isinstance(markup, str) or not markup:
        return None
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", htmllib.unescape(htmllib.unescape(markup))))
    for found in _MONEY_RANGE.finditer(text):
        numbers = [float(n.replace(",", "")) for n in re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?", found.group(0))]
        scaled = [n * 1000 if "k" in found.group(0).lower() and n < 1000 else n for n in numbers]
        if scaled and min(scaled) >= 15 and max(scaled) >= 1000 or (scaled and max(scaled) < 1000 and min(scaled) >= 15):
            return found.group(0).strip()
    return None


def _money(cents: Any) -> str | None:
    if isinstance(cents, (int, float)) and cents > 0:
        return f"${cents / 100:,.0f}"
    return None


@dataclass
class AtsInfo:
    live: bool | None = None  # True open, False clearly gone, None could not tell
    posted: dt.date | None = None
    pay: str | None = None  # pay range the posting states, when its data includes one
    checked: bool = False  # the system itself answered, so no page check is needed


def _day_from_ms(value: Any) -> dt.date | None:
    if isinstance(value, (int, float)) and value > 0:
        day = dt.datetime.fromtimestamp(value / 1000, tz=dt.timezone.utc).date()
        return day if day <= dt.date.today() else None
    return None


def workday_api_url(url: str) -> str | None:
    """Workday serves each posting as data at /wday/cxs/<company>/<site>/job/<path>."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host.endswith(".myworkdayjobs.com"):
        return None
    segs = [p for p in parts.path.split("/") if p]
    if segs and _LANG.fullmatch(segs[0]):
        segs = segs[1:]
    if "job" not in segs:
        return None
    at = segs.index("job")
    if at < 1 or at + 1 >= len(segs):
        return None
    return f"https://{host}/wday/cxs/{host.split('.')[0]}/{segs[at - 1]}/job/{'/'.join(segs[at + 1:])}"


def workday_info(status: int, data: Any) -> AtsInfo:
    if status in (404, 410):
        return AtsInfo(live=False, checked=True)
    info = data.get("jobPostingInfo") if isinstance(data, dict) else None
    if status != 200 or not isinstance(info, dict):
        return AtsInfo()
    from app.services.discovery.web_search import extract_posted_date  # same "Posted 30+ days ago" reader

    posted = parse_posted_date(info.get("startDate")) or extract_posted_date(f"Posted {info.get('postedOn', '')}")
    live = False if info.get("canApply") is False else True
    return AtsInfo(live=live, posted=posted, pay=extract_pay_text(info.get("jobDescription")), checked=True)


def greenhouse_ref(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host not in ("boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io"):
        return None
    segs = [p for p in parts.path.split("/") if p]
    if len(segs) >= 3 and segs[1] == "jobs" and segs[2].isdigit():
        return segs[0], segs[2]
    return None


def greenhouse_info(status: int, data: Any) -> AtsInfo:
    if status in (404, 410):
        return AtsInfo(live=False, checked=True)
    if status != 200 or not isinstance(data, dict):
        return AtsInfo()
    pay = None
    ranges = data.get("pay_input_ranges")
    if isinstance(ranges, list) and ranges and isinstance(ranges[0], dict):
        low, high = _money(ranges[0].get("min_cents")), _money(ranges[0].get("max_cents"))
        pay = f"{low} - {high}" if low and high else low or high
    return AtsInfo(live=True, posted=parse_posted_date(data.get("first_published")), pay=pay or extract_pay_text(data.get("content")), checked=True)


def ashby_ref(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    if (parts.hostname or "").lower() != "jobs.ashbyhq.com":
        return None
    segs = [p for p in parts.path.split("/") if p]
    if len(segs) >= 2 and re.fullmatch(r"[0-9a-fA-F-]{20,}", segs[1]):
        return segs[0], segs[1].lower()
    return None


def ashby_info(status: int, data: Any, job_id: str) -> AtsInfo:
    if status != 200 or not isinstance(data, dict) or not isinstance(data.get("jobs"), list) or not data["jobs"]:
        return AtsInfo()
    for job in data["jobs"]:
        if isinstance(job, dict) and str(job.get("id", "")).lower() == job_id:
            comp = job.get("compensation") if isinstance(job.get("compensation"), dict) else {}
            pay = comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary")
            return AtsInfo(
                live=job.get("isListed") is not False,
                posted=parse_posted_date(job.get("publishedAt")),
                pay=pay if isinstance(pay, str) and pay.strip() else extract_pay_text(job.get("descriptionHtml")),
                checked=True,
            )
    return AtsInfo(live=False, checked=True)  # the board is there and this posting is not on it


def lever_ref(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    if (parts.hostname or "").lower() not in ("jobs.lever.co", "jobs.eu.lever.co"):
        return None
    segs = [p for p in parts.path.split("/") if p]
    if len(segs) >= 2 and re.fullmatch(r"[0-9a-fA-F-]{20,}", segs[1]):
        return segs[0], segs[1]
    return None


def lever_info(status: int, data: Any) -> AtsInfo:
    if status in (404, 410):
        return AtsInfo(live=False, checked=True)
    if status != 200 or not isinstance(data, dict):
        return AtsInfo()
    pay = None
    rng = data.get("salaryRange")
    if isinstance(rng, dict) and rng.get("min") and rng.get("max"):
        pay = f"${rng['min']:,.0f} - ${rng['max']:,.0f}" if isinstance(rng["min"], (int, float)) else None
    pay = pay or extract_pay_text(data.get("salaryDescription")) or extract_pay_text(data.get("descriptionPlain"))
    return AtsInfo(live=True, posted=_day_from_ms(data.get("createdAt")), pay=pay, checked=True)


async def _get_json(client: httpx.AsyncClient, url: str) -> tuple[int, Any]:
    resp = await client.get(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, None


async def inspect(url: str, client: httpx.AsyncClient, ashby_boards: dict[str, tuple[int, Any]]) -> AtsInfo:
    """Open/closed and posted date from the posting's own system. AtsInfo() (all unknown) for any other site or on error."""
    try:
        api = workday_api_url(url)
        if api:
            return workday_info(*await _get_json(client, api))
        gh = greenhouse_ref(url)
        if gh:
            return greenhouse_info(*await _get_json(client, f"https://boards-api.greenhouse.io/v1/boards/{gh[0]}/jobs/{gh[1]}?pay_transparency=true"))
        ab = ashby_ref(url)
        if ab:
            if ab[0] not in ashby_boards:
                ashby_boards[ab[0]] = await _get_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{ab[0]}?includeCompensation=true")
            return ashby_info(*ashby_boards[ab[0]], ab[1])
        lv = lever_ref(url)
        if lv:
            return lever_info(*await _get_json(client, f"https://api.lever.co/v0/postings/{lv[0]}/{lv[1]}"))
    except Exception:
        return AtsInfo()
    return AtsInfo()
