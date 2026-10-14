"""
Search quality test set: a fixed list of searches, a pool of the jobs different search variants returned for each, labels
saying which of those jobs are relevant, and the scoring that turns runs plus labels into numbers.

Why it exists: without it "better" is a feeling. With it, every change to search is a before and after on the same searches.

Files
  backend/eval/test_searches.json   the searches and what "relevant" means for each (in the repository)
  backend/data/eval/runs/*.json     what each variant returned (local, rebuilt by running the script)
  backend/data/eval/pool.json       every distinct job any run returned, per search (local)
  backend/data/eval/labels.json     relevant / not relevant / unsure per job (local, so a git pull never conflicts with it)
"""

from __future__ import annotations

import json
import math
import os
import statistics
import tempfile
import threading
from pathlib import Path
from typing import Any

from app.config import DEFAULT_DATA_DIR
from app.schemas.job_search import JobSearchIn
from app.services.jobcache.text import fold

SEARCHES_FILE = Path(__file__).resolve().parents[2] / "eval" / "test_searches.json"
LABEL_VALUES = ("rel", "no", "unsure")
TODAY_ARMS = {"saved", "full"}  # the variants that show what today's search puts in front of the user
_LOCK = threading.Lock()


def data_dir() -> Path:
    return DEFAULT_DATA_DIR / "eval"


def runs_dir() -> Path:
    return data_dir() / "runs"


# ---- the searches ----------------------------------------------------------------------------------------------

def load_searches() -> list[dict[str, Any]]:
    """The test searches, each with a validated `criteria` (a JobSearchIn) next to its id, group and relevance rubric."""
    raw = json.loads(SEARCHES_FILE.read_text(encoding="utf-8"))
    out = []
    seen: set[str] = set()
    for entry in raw:
        sid = entry["id"]
        if sid in seen:
            raise ValueError(f"duplicate test search id: {sid}")
        seen.add(sid)
        out.append({**entry, "criteria": JobSearchIn(**entry["criteria"])})
    return out


def search_by_id(search_id: str) -> dict[str, Any] | None:
    return next((s for s in load_searches() if s["id"] == search_id), None)


def describe(criteria: JobSearchIn) -> list[str]:
    """Short chips for the screen: what this search asked for."""
    chips = [criteria.titles]
    if criteria.location:
        chips.append(criteria.location)
    if criteria.work_type != "any":
        chips.append(criteria.work_type)
    if criteria.target_salary:
        chips.append(f"${criteria.target_salary:,}+")
    if criteria.keywords:
        chips.append(f"keyword: {criteria.keywords}")
    chips.append(f"last {criteria.posted_within_days} days" if criteria.posted_within_days else "any date")
    return chips


# ---- identity of a job -----------------------------------------------------------------------------------------

def city_of(location: str | None) -> str:
    return fold((location or "").split(",")[0])


def job_key(item: dict[str, Any]) -> str:
    """
    One key per real-world job: employer, title and city. The same opening seen at two addresses (the employer's own page and a
    job board) gets one key, so it is labeled once and counted as a duplicate when a search shows it twice.
    """
    return f"{fold(item.get('company'))}|{fold(item.get('title'))}|{city_of(item.get('location'))}"


def slim(item: dict[str, Any]) -> dict[str, Any]:
    """The fields kept about a result (public posting facts only)."""
    posted = item.get("posted_at")
    return {
        "title": item.get("title") or "",
        "company": item.get("company") or "",
        "location": item.get("location"),
        "pay": item.get("salary_text"),
        "posted": posted.isoformat() if hasattr(posted, "isoformat") else posted,
        "url": item.get("url") or "",
        "live": item.get("live"),
    }


# ---- files -----------------------------------------------------------------------------------------------------

def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_pool() -> dict[str, dict[str, Any]]:
    return read_json(data_dir() / "pool.json", {})


def load_labels() -> dict[str, dict[str, Any]]:
    return read_json(data_dir() / "labels.json", {})


def load_runs(names: list[str] | None = None) -> list[dict[str, Any]]:
    out = []
    for p in sorted(runs_dir().glob("*.json")) if runs_dir().exists() else []:
        run = read_json(p, None)
        if isinstance(run, dict) and (not names or run.get("name") in names or p.stem in names):
            out.append(run)
    return out


# ---- pool ------------------------------------------------------------------------------------------------------

def build_pool(runs: list[dict[str, Any]], existing: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Every distinct job any run returned, per search, with which variants returned it and at which position."""
    pool: dict[str, dict[str, Any]] = {sid: {k: dict(v) for k, v in jobs.items()} for sid, jobs in (existing or {}).items()}
    for run in runs:
        arm = run.get("arm", "?")
        for s in run.get("searches", []):
            jobs = pool.setdefault(s["id"], {})
            for pos, item in enumerate(s.get("items", []), start=1):
                key = job_key(item)
                row = jobs.setdefault(key, {**slim(item), "arms": {}})
                row["arms"][arm] = pos
                if not row.get("url") and item.get("url"):
                    row["url"] = item["url"]
    return pool


# ---- labels ----------------------------------------------------------------------------------------------------

def set_label(search_id: str, key: str, label: str | None, *, by: str = "user", why: str | None = None, record: dict[str, Any] | None = None) -> dict[str, Any]:
    """Saves (or clears, with None) one label. `record` carries the job's facts so the label stays meaningful on its own."""
    if label is not None and label not in LABEL_VALUES:
        raise ValueError("label must be rel, no, unsure or null")
    with _LOCK:
        labels = load_labels()
        per = labels.setdefault(search_id, {})
        if label is None:
            per.pop(key, None)
        else:
            old = per.get(key, {})
            per[key] = {**old, **(record or {}), "label": label, "by": by, "why": why if why is not None else old.get("why")}
        write_json(data_dir() / "labels.json", labels)
        return per.get(key, {})


def confirm_ai_labels(search_id: str) -> int:
    """The person agrees with every AI suggestion on this search: they become theirs."""
    with _LOCK:
        labels = load_labels()
        n = 0
        for rec in labels.get(search_id, {}).values():
            if rec.get("by") == "ai":
                rec["by"] = "user"
                n += 1
        write_json(data_dir() / "labels.json", labels)
        return n


def add_manual(search_id: str, item: dict[str, Any], source: str, in_today: bool) -> tuple[str, dict[str, Any]]:
    """A job the person found by hand on a big job site. Returns its key and the saved record."""
    key = job_key(item)
    with _LOCK:
        labels = load_labels()
        per = labels.setdefault(search_id, {})
        rec = per.get(key, {})
        rec.update({**slim(item), "src": source, "manual": True, "in_today": in_today})
        rec.setdefault("label", None)
        rec.setdefault("by", "user")
        per[key] = rec
        write_json(data_dir() / "labels.json", labels)
        return key, rec


def rows_for(search_id: str) -> list[dict[str, Any]]:
    """The jobs to show for one search: everything in the pool plus the jobs added by hand, with any label."""
    pool = load_pool().get(search_id, {})
    labels = load_labels().get(search_id, {})
    rows = []
    for key in list(pool) + [k for k in labels if k not in pool]:
        base = pool.get(key) or {}
        lab = labels.get(key, {})
        arms = base.get("arms") or {}
        manual = bool(lab.get("manual"))
        rec = {**{k: lab.get(k) for k in ("title", "company", "location", "pay", "posted", "url")}, **{k: v for k, v in base.items() if k != "arms"}}
        rows.append(
            {
                "key": key,
                **{k: rec.get(k) for k in ("title", "company", "location", "pay", "posted", "url")},
                "arms": sorted(arms),
                "source": lab.get("src") if manual else "today",
                "in_today": bool(set(arms) & TODAY_ARMS) or bool(lab.get("in_today")),
                "label": lab.get("label"),
                "by": lab.get("by"),
                "why": lab.get("why"),
            }
        )
    # today's results first (in their order), then the rest of the pool, then jobs added by hand
    def order(r: dict[str, Any]) -> tuple[int, int]:
        arms = (pool.get(r["key"]) or {}).get("arms") or {}
        pos = min((arms[a] for a in TODAY_ARMS if a in arms), default=None)
        if pos is not None:
            return (0, pos)
        return (1, 0) if r["arms"] else (2, 0)

    rows.sort(key=order)
    return rows


def progress(search_id: str) -> dict[str, int]:
    rows = rows_for(search_id)
    return {
        "total": len(rows),
        "labeled": sum(1 for r in rows if r["label"]),
        "by_you": sum(1 for r in rows if r["label"] and r["by"] == "user"),
    }


# ---- scoring ---------------------------------------------------------------------------------------------------

def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    return vals[min(len(vals) - 1, max(0, math.ceil(p * len(vals)) - 1))]


RESULT_CAP = 15  # the most results one search can show


def score_run(run: dict[str, Any], labels: dict[str, dict[str, Any]], *, only_user: bool = False, cap: int = RESULT_CAP) -> dict[str, Any]:
    """
    Per search and overall: how many of the results are relevant, how many known relevant jobs the search missed, duplicates,
    dead links, time and cost. `only_user` ignores AI suggestions (they count as unlabeled).

    "Found" is measured against the best a search could do: with 34 known relevant jobs and room for 15 results, finding 15 is a
    perfect score, not 44%. Otherwise a search would look bad for showing only what fits on the screen.
    """
    per_search = []
    for s in run.get("searches", []):
        sid = s["id"]
        lab = {k: v for k, v in labels.get(sid, {}).items() if v.get("label") and (not only_user or v.get("by") == "user")}
        items = s.get("items", [])
        keys = [job_key(i) for i in items]
        rel = [k for k in keys if lab.get(k, {}).get("label") == "rel"]
        no = [k for k in keys if lab.get(k, {}).get("label") == "no"]
        unsure = [k for k in keys if lab.get(k, {}).get("label") == "unsure"]
        unlabeled = [k for k in keys if k not in lab]
        known_rel = {k for k, v in lab.items() if v["label"] == "rel"}
        found = known_rel & set(keys)
        missed = sorted(known_rel - set(keys))
        per_search.append(
            {
                "id": sid,
                "returned": len(items),
                "relevant": len(rel),
                "not_relevant": len(no),
                "unsure": len(unsure),
                "unlabeled": len(unlabeled),
                "precision": (len(rel) / (len(rel) + len(no))) if (rel or no) else None,
                "known_relevant": len(known_rel),
                "found_relevant": len(found),
                "recall": (len(found) / min(len(known_rel), cap)) if known_rel else None,
                "missed": [lab[k].get("title", k) + " at " + lab[k].get("company", "") for k in missed][:10],
                "duplicates": len(keys) - len(set(keys)),
                "dead_links": sum(1 for i in items if i.get("live") is False),
                "checked_links": sum(1 for i in items if i.get("live") is not None),
                "seconds": s.get("seconds"),
                "cost_usd": s.get("cost_usd"),
                "error": s.get("error") or "",
            }
        )
    precs = [p["precision"] for p in per_search if p["precision"] is not None]
    recs = [p["recall"] for p in per_search if p["recall"] is not None]
    secs = [p["seconds"] for p in per_search if p["seconds"] is not None]
    costs = [p["cost_usd"] for p in per_search if p["cost_usd"] is not None]
    checked = sum(p["checked_links"] for p in per_search)
    total = {
        "searches": len(per_search),
        "with_results": sum(1 for p in per_search if p["returned"]),
        "avg_results": statistics.fmean(p["returned"] for p in per_search) if per_search else None,
        "avg_relevant": statistics.fmean(p["relevant"] for p in per_search) if per_search else None,
        "avg_precision": statistics.fmean(precs) if precs else None,
        "avg_recall": statistics.fmean(recs) if recs else None,
        "searches_with_duplicates": sum(1 for p in per_search if p["duplicates"]),
        "duplicates": sum(p["duplicates"] for p in per_search),
        "dead_link_share": (sum(p["dead_links"] for p in per_search) / checked) if checked else None,
        "median_seconds": statistics.median(secs) if secs else None,
        "p95_seconds": _percentile(secs, 0.95),
        "avg_cost_usd": statistics.fmean(costs) if costs else None,
        "unlabeled": sum(p["unlabeled"] for p in per_search),
        "labeled_by_you": sum(1 for per in labels.values() for v in per.values() if v.get("label") and v.get("by") == "user"),
        "labeled_by_ai": sum(1 for per in labels.values() for v in per.values() if v.get("label") and v.get("by") == "ai"),
    }
    return {"run": run.get("name"), "arm": run.get("arm"), "total": total, "per_search": per_search}


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.0f}%"


def _num(v: float | None, fmt: str = "{:.1f}") -> str:
    return "n/a" if v is None else fmt.format(v)


def format_report(scores: list[dict[str, Any]], titles: dict[str, str] | None = None) -> str:
    """A plain-text report: overall numbers per run, then one line per search."""
    titles = titles or {}
    lines = ["# Search quality report", ""]
    lines.append("| Run | Searches | Avg results | Avg relevant results | Relevant share | Best possible found | Duplicates | Dead links | Median s | Slowest 5% s | Avg cost |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for sc in scores:
        t = sc["total"]
        lines.append(
            f"| {sc['run']} ({sc['arm']}) | {t['with_results']}/{t['searches']} | {_num(t['avg_results'])} | {_num(t['avg_relevant'])} | {_pct(t['avg_precision'])} | {_pct(t['avg_recall'])} | "
            f"{t['duplicates']} in {t['searches_with_duplicates']} searches | {_pct(t['dead_link_share'])} | {_num(t['median_seconds'])} | {_num(t['p95_seconds'])} | "
            f"{_num(t['avg_cost_usd'], '${:.4f}')} |"
        )
    for sc in scores:
        t = sc["total"]
        lines += ["", f"## {sc['run']} ({sc['arm']})", f"Labels: {t['labeled_by_you']} by you, {t['labeled_by_ai']} AI suggestions. Results not yet labeled: {t['unlabeled']}.", ""]
        lines.append("| Search | Returned | Relevant | Not relevant | Unsure | Unlabeled | Missed relevant | Dup | Dead | Seconds | Cost |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for p in sc["per_search"]:
            miss = f"{p['known_relevant'] - p['found_relevant']} of {p['known_relevant']}" if p["known_relevant"] else "n/a"
            lines.append(
                f"| {titles.get(p['id'], p['id'])} | {p['returned']} | {p['relevant']} | {p['not_relevant']} | {p['unsure']} | {p['unlabeled']} | {miss} | "
                f"{p['duplicates']} | {p['dead_links']}/{p['checked_links']} | {_num(p['seconds'])} | {_num(p['cost_usd'], '${:.4f}')} |{(' ERROR ' + p['error']) if p['error'] else ''}"
            )
    return "\n".join(lines)
