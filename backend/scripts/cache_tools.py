"""
Two safe helpers for the saved job lists (the job cache). Neither touches your job database (job_agent.db).

  cd backend
  python -m scripts.cache_tools coverage                  # how complete the saved lists are, by hiring system (read only)
  python -m scripts.cache_tools coverage --db PATH        # the same for another copy, such as the frozen test copy
  python -m scripts.cache_tools reread --db PATH [--only greenhouse,lever]
                                                          # re-reads employers and fills in details on postings the copy ALREADY has.
                                                          # It adds no postings and closes none, so a before and after test stays fair.

`reread` refuses to run on the live saved lists unless you add --live (the normal background refresh does the same job there).
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

from app.config import settings
from app.services.jobcache.readers import ReaderError, Throttle, make_client, read_employer
from app.services.jobcache.store import JobCache, now_ts

# column -> label shown in the report; only columns the copy actually has are shown
FIELDS = {
    "pay_text": "pay",
    "posted_at": "posted date",
    "work_type": "work type",
    "description": "description",
    "lat": "coordinates",
    "agency": "agency flag set",
}


def cmd_coverage(args: argparse.Namespace) -> int:
    path = Path(args.db or settings.JOB_CACHE_PATH)
    if not path.exists():
        print(f"No saved job lists at {path}.")
        return 1
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    have = {r["name"] for r in conn.execute("PRAGMA table_info(postings)")}
    cols = [c for c in FIELDS if c in have]
    parts = ", ".join(f"SUM(CASE WHEN p.{c} IS NOT NULL AND p.{c} != '' THEN 1 ELSE 0 END) AS {c}" for c in cols)
    sql = (
        f"SELECT e.ats AS ats, COUNT(*) AS n{', ' + parts if parts else ''} FROM postings p JOIN employers e ON e.id = p.employer_id "
        "WHERE p.closed_at IS NULL AND e.enabled = 1 GROUP BY e.ats ORDER BY n DESC"
    )
    rows = conn.execute(sql).fetchall()
    total = sum(r["n"] for r in rows) or 1
    head = f"{'system':16}{'open':>8}" + "".join(f"{FIELDS[c]:>16}" for c in cols)
    print(f"Saved job lists: {path}\n{head}")
    sums = {c: 0 for c in cols}
    for r in rows:
        print(f"{r['ats']:16}{r['n']:>8}" + "".join(f"{(r[c] or 0) / r['n']:>15.0%} " for c in cols))
        for c in cols:
            sums[c] += r[c] or 0
    print(f"{'ALL':16}{total:>8}" + "".join(f"{sums[c] / total:>15.0%} " for c in cols))
    if "lat" not in have:
        print("\n(no coordinates column in this copy)")
    return 0


async def _reread(args: argparse.Namespace) -> int:
    path = Path(args.db)
    if not path.exists():
        print(f"{path} does not exist.")
        return 1
    if path.resolve() == Path(settings.JOB_CACHE_PATH).resolve() and not args.live:
        print("That is the live saved lists. Add --live to confirm, or point --db at a copy.")
        return 1
    cache = JobCache(str(path))
    only = {s.strip() for s in args.only.split(",")} if args.only else None
    emps = [e for e in cache.list_employers() if e["enabled"] and (not only or e["ats"] in only)]
    print(f"Re-reading {len(emps)} employers in {path.name}. No postings will be added or closed.")
    throttle, sem = Throttle(), asyncio.Semaphore(4)
    tally = {"ok": 0, "failed": 0, "updated": 0}

    async with make_client() as client:

        async def one(e: dict) -> None:
            async with sem:
                try:
                    res = await read_employer(e["ats"], e["identifier"], client, throttle)
                except (ReaderError, Exception) as exc:  # one employer must never stop the rest
                    tally["failed"] += 1
                    print(f"  could not read {e['name']} ({e['ats']}): {str(exc)[:100]}")
                    return
                with cache.session() as db:
                    open_ids = {r["ext_id"] for r in db.execute("SELECT ext_id FROM postings WHERE employer_id = ? AND closed_at IS NULL", (e["id"],))}
                keep = [p for p in res.postings if p.ext_id in open_ids]
                cache.apply_refresh(e["id"], keep, now_ts(), 6.0, close_missing=False)
                tally["ok"] += 1
                tally["updated"] += len(keep)

        await asyncio.gather(*(one(e) for e in emps))
    print(f"Done: {tally['ok']} employers read, {tally['failed']} failed, {tally['updated']} postings refreshed.")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("coverage")
    c.add_argument("--db")
    r = sub.add_parser("reread")
    r.add_argument("--db", required=True)
    r.add_argument("--only", help="comma separated hiring systems, e.g. greenhouse,lever,ashby")
    r.add_argument("--live", action="store_true")
    args = p.parse_args()
    sys.exit(cmd_coverage(args) if args.cmd == "coverage" else asyncio.run(_reread(args)))


if __name__ == "__main__":
    main()
