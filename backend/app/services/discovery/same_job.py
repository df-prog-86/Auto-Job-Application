"""
When are two search results the same job? Only on evidence, because wrongly joining two real openings hides one of them.

  * Two different job numbers on the same hiring board are two jobs, always (a company can post the same title in two cities).
  * The same job number on the same board, the same apply link, or the same requisition number is one job.
  * Otherwise two results are one job only when their descriptions are nearly word for word the same.
  * Same company and title alone is never enough.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.services.jobcache.keys import loose_keys

_WD_REQ = re.compile(r"_([A-Za-z]{1,4}-?\d{3,})(?:/|$)")
_REQ_PARAMS = ("jid", "gh_jid", "req", "reqid", "req_id", "requisition", "requisitionid", "requisition_id", "jobid", "job_id", "jr_id", "rid")
_TITLE_REQ = re.compile(r"\b(?:req(?:uisition)?\.?\s*(?:id|no\.?|#)?\s*[:#]?\s*|jr[-\s]?|r-)(\d{4,})\b", re.I)
SIMILAR = 0.85


def job_ref(url: str) -> tuple[str, str] | None:
    """(board, job number) when the address is one of the hiring systems we can read a job number from, else None."""
    parts = urlsplit((url or "").strip())
    host = parts.netloc.lower().removeprefix("www.")
    segs = [s for s in parts.path.split("/") if s]
    if host.endswith("greenhouse.io") and "jobs" in segs and segs.index("jobs") + 1 < len(segs):
        board = segs[0] if segs[0] != "jobs" else ""
        return (f"greenhouse:{board}", segs[segs.index("jobs") + 1])
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and len(segs) >= 2:
        return (f"lever:{segs[0].lower()}", segs[1].lower())
    if host == "jobs.ashbyhq.com" and len(segs) >= 2:
        return (f"ashby:{segs[0].lower()}", segs[1].lower())
    if host.endswith(".myworkdayjobs.com"):
        m = _WD_REQ.search(parts.path + "/")
        if m:
            site = [s for s in segs if not re.fullmatch(r"[a-z]{2}-[A-Za-z]{2}", s)][:1]
            return (f"workday:{host}:{site[0].lower() if site else ''}", m.group(1).lower())
    if host.endswith("smartrecruiters.com") and len(segs) >= 2:
        m = re.match(r"(\d{6,})", segs[1])
        if m:
            return (f"smartrecruiters:{segs[0].lower()}", m.group(1))
    return None


def req_ids(item: dict[str, Any]) -> set[str]:
    """Requisition numbers an item states: in its address or in its title ("Analyst (Req 48213)")."""
    out: set[str] = set()
    url = item.get("url") or ""
    query = parse_qs(urlsplit(url).query)
    for name in _REQ_PARAMS:
        for value in query.get(name, []) + query.get(name.upper(), []):
            if value.strip():
                out.add(value.strip().lower())
    ref = job_ref(url)
    if ref:
        out.add(ref[1])
    for m in _TITLE_REQ.finditer(item.get("title") or ""):
        out.add(m.group(1))
    return out


def _shingles(text: str, n: int = 5) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(words[i : i + n]) for i in range(max(len(words) - n + 1, 0))}


def similarity(a: str | None, b: str | None) -> float:
    """0 to 1: how much of two texts is the same run of five words. 0 when either is too short to judge."""
    sa, sb = _shingles(a or ""), _shingles(b or "")
    if len(sa) < 12 or len(sb) < 12:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def same_posting(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ra, rb = job_ref(a["url"]), job_ref(b["url"])
    if ra and rb and ra[0] == rb[0]:
        return ra[1] == rb[1]  # one board: the job numbers decide, nothing else can overrule them
    if loose_keys(a["url"]) & loose_keys(b["url"]):
        return True
    ida, idb = req_ids(a), req_ids(b)
    if ida & idb:
        return True
    return similarity(a.get("_desc"), b.get("_desc")) >= SIMILAR


def clusters(items: list[dict[str, Any]], group_key) -> list[list[dict[str, Any]]]:
    """Items grouped into sets of the same posting. Only items that share `group_key` (a cheap pre-filter) are ever compared."""
    groups: dict[str, list[list[dict[str, Any]]]] = {}
    for item in items:
        key = group_key(item)
        placed = False
        for cluster in groups.setdefault(key, []):
            if any(same_posting(item, other) for other in cluster):
                cluster.append(item)
                placed = True
                break
        if not placed:
            groups[key].append([item])
    return [c for g in groups.values() for c in g]
