"""
Two safe helpers for the saved job lists (the job cache). Neither touches your job database (job_agent.db).

  cd backend
  python -m scripts.cache_tools coverage                  # how complete the saved lists are, by hiring system (read only)
  python -m scripts.cache_tools coverage --db PATH        # the same for another copy, such as the frozen test copy
  python -m scripts.cache_tools reread --db PATH [--only greenhouse,lever]
                                                          # re-reads employers and fills in details on postings the copy ALREADY has.
                                                          # It adds no postings and closes none, so a before and after test stays fair.

  python -m scripts.cache_tools probe 'workday:HOST|TENANT|SITE' ...
                                                          # reads those employers' public job lists and prints counts and sample titles.
                                                          # Saves nothing; this is how a candidate is checked before it is added.
  python -m scripts.cache_tools add --from-file FILE [--apply] [--skip TEXT]
                                                          # adds the employers in FILE that pass the standing rule (reads cleanly, enough jobs,
                                                          # mostly US, not an agency) and reads them. Dry run unless --apply. Stop the app first.
  python -m scripts.cache_tools sites [--db PATH] [--max-hosts 60]
                                                          # asks Common Crawl's public web index which OTHER career sites each Workday
                                                          # employer we already read has (one company often runs several). Read only:
                                                          # it prints a list; nothing is added to the saved lists.

`reread` refuses to run on the live saved lists unless you add --live (the normal background refresh does the same job there).
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

from app.config import settings
from app.services.jobcache import geo
from app.services.jobcache.text import parse_location_query
from app.services.jobcache.readers import ReaderError, Throttle, make_client, read_employer
from app.services.jobcache.store import JobCache, now_ts

# column -> label shown in the report; only columns the copy actually has are shown
FIELDS = {
    "pay_text": "pay",
    "posted_at": "posted date",
    "work_type": "work type",
    "description": "description",
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
    placed: dict[str, int] = {}  # open postings whose city has known coordinates
    for r in conn.execute(
        "SELECT e.ats AS ats, p.location AS loc, COUNT(*) AS n FROM postings p JOIN employers e ON e.id = p.employer_id "
        "WHERE p.closed_at IS NULL AND e.enabled = 1 AND p.location IS NOT NULL GROUP BY e.ats, p.location"
    ):
        q = parse_location_query(r["loc"])
        state = next(iter(q.states)) if len(q.states) == 1 else None
        if q.cities and geo.lookup(q.cities[0], state):
            placed[r["ats"]] = placed.get(r["ats"], 0) + r["n"]
    head = f"{'system':16}{'open':>8}" + "".join(f"{FIELDS[c]:>16}" for c in cols) + f"{'coordinates':>16}"
    print(f"Saved job lists: {path}\n{head}")
    sums = {c: 0 for c in cols}
    for r in rows:
        print(f"{r['ats']:16}{r['n']:>8}" + "".join(f"{(r[c] or 0) / r['n']:>15.0%} " for c in cols) + f"{placed.get(r['ats'], 0) / r['n']:>15.0%} ")
        for c in cols:
            sums[c] += r[c] or 0
    print(f"{'ALL':16}{total:>8}" + "".join(f"{sums[c] / total:>15.0%} " for c in cols) + f"{sum(placed.values()) / total:>15.0%} ")
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


_NOT_SITES = {"robots.txt", "sitemap.xml", "favicon.ico", "wday", "assets", "static"}


def sites_from_urls(urls: list[str], known: set[str]) -> dict[str, int]:
    """
    Workday career sites named by these addresses that are not already read: {"host|tenant|site": addresses seen}.
    Workday ignores capital letters in a site name ("External" and "external" are one site), so they are compared without them.
    """
    from app.services.jobcache.readers import employer_ref

    have = {k.lower() for k in known}
    found: dict[str, int] = {}
    spelled: dict[str, str] = {}
    for u in urls:
        ref = employer_ref(u)
        if not ref or ref[0] != "workday":
            continue
        site = ref[1].rsplit("|", 1)[-1]
        if site.lower() in _NOT_SITES or (len(site) == 2 and site.isalpha()) or ref[1].lower() in have:
            continue
        key = ref[1].lower()
        spelled.setdefault(key, ref[1])
        found[spelled[key]] = found.get(spelled[key], 0) + 1
    return found


_FOCUS = ("revenue cycle", "billing", "coding", "denial", "claims", "collections", "patient access", "patient financial", "reimbursement",
          "payer", "consult", "healthcare", "health care", "clinical", "nurse")


def probe_row(spec: str, postings: list, complete: bool, notes: list[str]) -> str:
    """One line per employer: how many jobs, how many look US based, how many match the focus words, and sample titles."""
    import re

    from app.services.jobcache.text import US_STATES

    def is_us(loc: str | None) -> bool:
        loc = loc or ""
        return "united states" in loc.lower() or "usa" in loc.lower() or any(t in US_STATES for t in re.findall(r"\b[A-Z]{2}\b", loc))

    n = len(postings)
    us = sum(1 for p in postings if is_us(p.location))
    focus = sum(1 for p in postings if any(w in (p.title or "").lower() for w in _FOCUS))
    sample = " ; ".join(p.title for p in postings[:2])
    flag = "" if complete else " PARTIAL"
    return f"{spec} | jobs {n}{flag} | US {us * 100 // max(n, 1)}% | focus-title {focus} | {sample[:110]}" + (f" | {'; '.join(notes)}" if notes else "")


async def _probe(args: argparse.Namespace) -> int:
    """Reads each named employer's public job list the way the app does and prints one line each. Saves nothing in the job lists."""
    throttle = Throttle()
    specs = list(args.employers)
    if args.from_file:
        specs += [ln.split("#")[0].strip().strip("'") for ln in Path(args.from_file).read_text().splitlines() if ln.split("#")[0].strip()]
    rows: list[str] = []
    async with make_client() as client:
        for spec in specs:
            system, _, ident = spec.partition(":")
            try:
                res = await read_employer(system, ident, client, throttle)
                row = probe_row(spec, res.postings, res.complete, res.notes)
            except Exception as exc:
                row = f"{spec} | COULD NOT BE READ: {type(exc).__name__}: {str(exc)[:100]}"
            rows.append(row)
            print(row, flush=True)
    if args.out:
        Path(args.out).expanduser().write_text("\n".join(rows) + "\n", encoding="utf-8")
        print(f"\nThe table was also saved to {args.out}. You can attach that file to the chat.")
    print("Nothing was added to the saved lists. These are only reads of the employers' public job lists.")
    return 0


def add_decision(system: str, ident: str, postings: list, args: argparse.Namespace) -> tuple[bool, str]:
    """The standing rule for adding an employer: reads cleanly, enough jobs, mostly US, not a staffing agency, not on the skip list."""
    from app.services.jobcache.agency import is_agency
    from app.services.jobcache.store import guess_name

    row = probe_row(f"{system}:{ident}", postings, True, [])
    n = len(postings)
    us = int(row.split("| US ")[1].split("%")[0])
    name = guess_name(system, ident)
    if any(s.lower() in f"{system}:{ident}".lower() for s in (args.skip or [])):
        return False, "on the skip list"
    if n < args.min_jobs:
        return False, f"only {n} jobs (rule: at least {args.min_jobs})"
    if us < args.min_us:
        return False, f"only {us}% US jobs (rule: at least {args.min_us}%)"
    if is_agency(name):
        return False, "looks like a staffing agency"
    return True, f"{n} jobs, {us}% US"


async def _add(args: argparse.Namespace) -> int:
    """Adds employers that pass the standing rule to the saved lists and reads them. Without --apply nothing is written."""
    specs = [ln.split("#")[0].strip().strip("'") for ln in Path(args.from_file).read_text().splitlines() if ln.split("#")[0].strip()]
    cache = JobCache()
    throttle = Throttle()
    added: list[tuple[int, str]] = []
    skipped = 0
    print(f"{len(specs)} employers to check. Rule: at least {args.min_jobs} jobs, at least {args.min_us}% US, not a staffing agency. "
          f"{'WRITING to the saved lists.' if args.apply else 'Dry run: nothing is written.'}")
    async with make_client() as client:
        for spec in specs:
            system, _, ident = spec.partition(":")
            try:
                res = await read_employer(system, ident, client, throttle)
            except Exception as exc:
                skipped += 1
                print(f"  SKIP  {spec}  could not be read ({type(exc).__name__})")
                continue
            ok, why = add_decision(system, ident, res.postings, args)
            if not ok:
                skipped += 1
                print(f"  SKIP  {spec}  {why}")
                continue
            if args.apply:
                eid, created = cache.upsert_employer(system, ident, res.name or "", args.source)
                if created:
                    cache.apply_refresh(eid, res.postings, now_ts(), 6.0, res.complete)
                    added.append((eid, spec))
                    print(f"  ADDED {spec}  {why}")
                else:
                    print(f"  HAVE  {spec}  already in the saved lists")
            else:
                added.append((0, spec))
                print(f"  ADD   {spec}  {why}")
    print(f"\n{len(added)} {'added' if args.apply else 'would be added'}, {skipped} skipped.")
    if args.apply:
        # employers whose lists stopped at Workday's old 2,000-job cutoff are read again so the rest of their jobs come in
        with cache.session() as db:
            capped = [r["id"] for r in db.execute(
                "SELECT e.id FROM employers e WHERE e.ats = 'workday' AND e.enabled = 1 AND "
                "(SELECT COUNT(*) FROM postings p WHERE p.employer_id = e.id AND p.closed_at IS NULL) = 2000")]
        if capped:
            from app.services.jobcache import service

            print(f"Reading {len(capped)} large Workday employer(s) again to pick up jobs past the old 2,000 cutoff ...")
            print(service.run_refresh(only_ids=capped, limit=len(capped), seed=False))
    return 0


async def _sites(args: argparse.Namespace) -> int:
    import json

    from app.services.safe_fetch import safe_get

    path = Path(args.db or settings.JOB_CACHE_PATH)
    if not path.exists():
        print(f"No saved lists at {path}.")
        return 1
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    idents = [r[0] for r in con.execute("SELECT identifier FROM employers WHERE ats = 'workday' AND enabled = 1")]
    con.close()
    known = set(idents)
    hosts = sorted({i.split("|")[0] for i in idents})[: args.max_hosts]
    print(f"{len(idents)} Workday career sites already read, on {len(hosts)} addresses. Asking Common Crawl (public, read only) about each.")
    try:
        info = json.loads((await safe_get("https://index.commoncrawl.org/collinfo.json", timeout=30)).text)
        api = info[0]["cdx-api"]
    except Exception as exc:
        print(f"Could not reach Common Crawl's index ({exc}). Nothing was changed.")
        return 1
    print(f"Using crawl {info[0].get('id')}.\n")
    total_new = 0
    for host in hosts:
        try:
            r = await safe_get(f"{api}?url={host}/*&output=json&fl=url&filter=status:200&limit=4000", timeout=60)
            urls = [json.loads(line)["url"] for line in r.text.splitlines() if line.startswith("{")] if r.status_code == 200 else []
        except Exception as exc:
            print(f"  {host}: could not ask ({type(exc).__name__})")
            urls = []
        if len(urls) >= 4000:
            print(f"  {host}: hit the 4,000 address limit, so the list for this one may be incomplete")
        new = sites_from_urls(urls, known)
        for ident, n in sorted(new.items(), key=lambda kv: -kv[1]):
            total_new += 1
            print(f"  NEW  {ident}   ({n} addresses seen)")
        await asyncio.sleep(1.5)  # a polite gap between questions
    print(f"\nDone: {total_new} career sites that are not read yet. Nothing was added; send me this list and I will check each one before anything is added.")
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
    s = sub.add_parser("sites")
    s.add_argument("--db")
    s.add_argument("--max-hosts", type=int, default=60)
    ad = sub.add_parser("add")
    ad.add_argument("--from-file", required=True)
    ad.add_argument("--apply", action="store_true", help="actually add them (without this it only shows what it would do)")
    ad.add_argument("--min-jobs", type=int, default=10)
    ad.add_argument("--min-us", type=int, default=60)
    ad.add_argument("--skip", action="append", help="leave out any employer whose address contains this text (repeatable)")
    ad.add_argument("--source", default="curated")
    pr = sub.add_parser("probe")
    pr.add_argument("--from-file", help="a file of specs, one per line (what 'eval_search gaps --write-probes' writes)")
    pr.add_argument("employers", nargs="*", help="system:identifier, e.g. 'workday:bilh.wd1.myworkdayjobs.com|bilh|external'")
    pr.add_argument("--samples", type=int, default=8, help="(no longer used)")
    pr.add_argument("--out", help="also save the table to this file")
    args = p.parse_args()
    if args.cmd == "add":
        sys.exit(asyncio.run(_add(args)))
    if args.cmd == "probe":
        sys.exit(asyncio.run(_probe(args)))
    if args.cmd == "sites":
        sys.exit(asyncio.run(_sites(args)))
    sys.exit(cmd_coverage(args) if args.cmd == "coverage" else asyncio.run(_reread(args)))


if __name__ == "__main__":
    main()
