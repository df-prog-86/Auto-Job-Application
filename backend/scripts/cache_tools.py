"""
Two safe helpers for the saved job lists (the job cache). Neither touches your job database (job_agent.db).

  cd backend
  python -m scripts.cache_tools coverage                  # how complete the saved lists are, by hiring system (read only)
  python -m scripts.cache_tools coverage --db PATH        # the same for another copy, such as the frozen test copy
  python -m scripts.cache_tools descriptions [--title 'revenue cycle']
                                                          # how many open postings have a saved description, by hiring system (read only)
  python -m scripts.cache_tools fill [--limit 150] [--system workday,icims] [--rounds 100] [--per-employer 15] [--pause 2]
                                                          # runs the description fill now: one batch, or many in a row for an overnight catch-up.
                                                          # Reads a few postings per employer per batch; safe to stop with Ctrl+C and to run again.
  python -m scripts.cache_tools reread --db PATH [--only greenhouse,lever]
                                                          # re-reads employers and fills in details on postings the copy ALREADY has.
                                                          # It adds no postings and closes none, so a before and after test stays fair.

  python -m scripts.cache_tools probe 'workday:HOST|TENANT|SITE' ...
                                                          # reads those employers' public job lists and prints counts and sample titles.
                                                          # Saves nothing; this is how a candidate is checked before it is added.
  python -m scripts.cache_tools add --from-file FILE [--apply] [--skip TEXT] [--resume-from EARLIER_OUTPUT] [--parallel N]
                                                          # adds the employers in FILE that pass the standing rule (reads cleanly, enough jobs,
                                                          # mostly US, not an agency) and reads them. Dry run unless --apply. Stop the app first.
  python -m scripts.cache_tools discover --system greenhouse,lever,...|all [--pages 6] [--limit 300] [--out FILE]
                                                          # asks Common Crawl for employer boards we do not read yet and writes them to FILE.
                                                          # Read only; check them afterwards with 'add --from-file FILE' (a dry run).
  python -m scripts.cache_tools recheck --system smartrecruiters
                                                          # reads that system's employers again now, so saved jobs get corrected details after a fix.
  python -m scripts.cache_tools usshare [--disable | --restore]
                                                          # lists employers whose jobs are mostly outside the US. --disable turns them off (reversible).
  python -m scripts.cache_tools reindex [--db PATH]
                                                          # builds the index of job description openings so search can read them. Safe to repeat or stop.
  python -m scripts.cache_tools industry [--retag]
                                                          # works out each employer's industry from its name and job titles, saves it, and prints
                                                          # how many employers and open jobs each industry has. Without --retag only blanks are filled.
  python -m scripts.cache_tools sites [--db PATH] [--max-hosts 60]
                                                          # asks Common Crawl's public web index which OTHER career sites each Workday
                                                          # employer we already read has (one company often runs several). Read only:
                                                          # it prints a list; nothing is added to the saved lists.

`reread` refuses to run on the live saved lists unless you add --live (the normal background refresh does the same job there).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
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


def cmd_descriptions(args: argparse.Namespace) -> int:
    """How many open postings have a saved description, by hiring system (read only). --title narrows it to titles holding those words."""
    path = Path(args.db or settings.JOB_CACHE_PATH)
    if not path.exists():
        print(f"No saved job lists at {path}.")
        return 1
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    where, params = "p.closed_at IS NULL AND e.enabled = 1", []
    for word in (args.title or "").split():
        where += " AND p.title LIKE ?"
        params.append(f"%{word}%")
    rows = conn.execute(
        "SELECT e.ats AS ats, COUNT(*) AS n, SUM(CASE WHEN p.description_z IS NOT NULL THEN 1 ELSE 0 END) AS withd "
        f"FROM postings p JOIN employers e ON e.id = p.employer_id WHERE {where} GROUP BY e.ats ORDER BY n DESC",
        params,
    ).fetchall()
    label = f' with "{args.title}" in the title' if args.title else ""
    print(f"Open postings{label}, and how many have a saved description ({path})")
    print(f"{'system':16}{'postings':>10}{'with description':>20}{'share':>9}")
    total = with_d = 0
    for r in rows:
        total += r["n"]
        with_d += r["withd"] or 0
        print(f"{r['ats']:16}{r['n']:>10}{(r['withd'] or 0):>20}{(r['withd'] or 0) / r['n']:>9.0%}")
    print(f"{'ALL':16}{total:>10}{with_d:>20}{(with_d / total if total else 0):>9.0%}")
    return 0


async def _fill(args: argparse.Namespace) -> int:
    """
    Runs the description fill now: one batch, or (with --rounds) many batches in a row for an overnight catch-up. Each batch reads a
    few postings from many different employers, so no one site is read hard. Safe to stop with Ctrl+C and to run again.
    """
    from app.services.jobcache import service

    cache = JobCache()
    if args.retry:
        again = cache.retry_unavailable([x.strip() for x in args.retry.split(",") if x.strip()] or None)
        print(f"{again} postings that could not be read before will be tried again.")
    skip = service.DESC_FILL_SYSTEMS_WITH_TEXT
    only = [x.strip() for x in args.system.split(",") if x.strip()] if args.system else None
    waiting_before = cache.count_postings_without_description(skip)
    total_saved = total_tried = 0
    why: dict[str, int] = {}
    seen: dict[str, dict[str, int]] = {}
    try:
        for n in range(1, max(args.rounds, 1) + 1):
            todo = cache.postings_without_description(args.limit, args.per_employer, skip, None, only)
            if not todo:
                print("Nothing left to read for those systems.")
                break
            saved = await service.read_missing_descriptions(todo, max_chars=service.DESC_FILL_CHARS, mark_failures=True, why=why)
            total_saved += saved
            total_tried += len(todo)
            for name, v in cache.description_outcomes([i for i, _u in todo]).items():
                row = seen.setdefault(name, {"saved": 0, "unreadable": 0})
                row["saved"] += v["saved"]
                row["unreadable"] += v["unreadable"]
            print(f"  batch {n}/{args.rounds}: tried {len(todo)}, saved {saved} (running total {total_saved})", flush=True)
            await asyncio.sleep(args.pause)
    except KeyboardInterrupt:
        print("Stopped. What was saved is kept.")
    print(f"Tried {total_tried} postings: {total_saved} descriptions saved, {total_tried - total_saved} could not be read (not tried again).")
    print(f"{'system':16}{'saved':>8}{'unreadable':>12}")
    for ats_name, v in sorted(seen.items()):
        print(f"{ats_name:16}{v['saved']:>8}{v['unreadable']:>12}")
    if why:
        print("Why postings could not be read:")
        for reason, count in sorted(why.items(), key=lambda kv: -kv[1]):
            print(f"  {count:>4}  {reason}")
    print(f"Postings still waiting for a description: {cache.count_postings_without_description(skip)} (was {waiting_before})")
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


_FOREIGN = re.compile(
    r"\b(canada|united kingdom|uk|england|scotland|wales|ireland|india|china|japan|germany|france|spain|italy|netherlands|poland|mexico|brazil|"
    r"argentina|australia|new zealand|singapore|hong kong|philippines|israel|korea|taiwan|vietnam|thailand|malaysia|indonesia|south africa|egypt|"
    r"saudi arabia|uae|emirates|turkey|sweden|norway|denmark|finland|belgium|switzerland|austria|portugal|czech|czechia|romania|hungary|colombia|"
    r"chile|peru|costa rica|ontario|quebec|british columbia|alberta|london|paris|dublin|toronto|vancouver|bangalore|bengaluru|mumbai|pune|hyderabad|"
    r"chennai|gurgaon|gurugram|noida|sydney|melbourne|tokyo|shanghai|beijing|manila|warsaw|krakow|berlin|munich|amsterdam|madrid|barcelona|milan|"
    r"rome|zurich|stockholm|copenhagen|oslo|apac|emea|latam)\b", re.I)


def location_kind(loc: str | None) -> str:
    """'us', 'foreign' or 'unknown' for one posting's place text. A US state (short or full name) or "United States" wins over a foreign-looking name."""
    from app.services.jobcache.text import STATE_BY_NAME, US_STATES, fold

    loc = loc or ""
    low = fold(loc)
    if (
        "united states" in low or re.search(r"\bUSA?\b", loc)
        or any(tok in US_STATES for tok in re.findall(r"(?<![A-Za-z])[A-Z]{2}(?![A-Za-z])", loc))
        or any(re.search(rf"\b{re.escape(name)}\b", low) for name in STATE_BY_NAME)
    ):
        return "us"
    from app.services.jobcache.text import _NON_US

    return "foreign" if _FOREIGN.search(loc) or any(f" {c} " in f" {low} " for c in _NON_US) else "unknown"


def us_stats(postings: list) -> tuple[int, int]:
    """(percent clearly US, percent clearly foreign); the rest could not be told from the place text (a hospital campus name, say)."""
    kinds = [location_kind(p.location) for p in postings]
    n = max(len(kinds), 1)
    return kinds.count("us") * 100 // n, kinds.count("foreign") * 100 // n


def probe_row(spec: str, postings: list, complete: bool, notes: list[str]) -> str:
    """One line per employer: how many jobs, how many look US based or foreign, how many match the focus words, and sample titles."""
    n = len(postings)
    us, foreign = us_stats(postings)
    focus = sum(1 for p in postings if any(w in (p.title or "").lower() for w in _FOCUS))
    sample = " ; ".join(p.title for p in postings[:2])
    flag = "" if complete else " PARTIAL"
    return f"{spec} | jobs {n}{flag} | US {us}% | foreign {foreign}% | focus-title {focus} | {sample[:110]}" + (f" | {'; '.join(notes)}" if notes else "")


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
    """
    The standing rule for adding an employer: reads cleanly, enough jobs, not mostly foreign, not a staffing agency, not on the skip
    list. Places that cannot be told (a hospital campus name) are not held against it. An employer you name with --include skips
    the place check.
    """
    from app.services.jobcache.agency import is_agency
    from app.services.jobcache.store import guess_name

    n = len(postings)
    us, foreign = us_stats(postings)
    name = guess_name(system, ident)
    key = f"{system}:{ident}".lower()
    if any(s.lower() in key for s in (args.skip or [])):
        return False, "on the skip list"
    if n < args.min_jobs:
        return False, f"only {n} jobs (rule: at least {args.min_jobs})"
    included = any(s.lower() in key for s in (getattr(args, "include", None) or []))
    keep = getattr(args, "keep_us_jobs", 15)
    enough_us = us * n // 100 >= keep  # a US employer with many offices abroad (Amgen, BCG) still has real US jobs worth having
    if not included and not enough_us and foreign > 100 - args.min_us:
        return False, f"{foreign}% of jobs are outside the US (rule: at most {100 - args.min_us}%)"
    if not included and not enough_us and us < 10 and foreign > 20:
        return False, f"only {us}% clearly US and {foreign}% outside the US"
    if is_agency(name):
        return False, "looks like a staffing agency"
    return True, f"{n} jobs, {us}% US, {foreign}% outside the US" + (", named by you" if included else "")


def _already_judged(paths: list[str]) -> set[str]:
    """Employers an earlier `add` run already decided on, read from its saved output. A read that failed is not counted, so it is tried again."""
    out: set[str] = set()
    for path in paths:
        for line in Path(path).read_text(errors="ignore").splitlines():
            parts = line.split(None, 2)
            if len(parts) < 2 or parts[0] not in ("ADD", "ADDED", "HAVE", "SKIP"):
                continue
            if parts[0] == "SKIP" and len(parts) > 2 and parts[2].startswith("could not be read"):
                continue
            out.add(parts[1])
    return out


async def _add(args: argparse.Namespace) -> int:
    """Adds employers that pass the standing rule to the saved lists and reads them. Without --apply nothing is written."""
    specs = [ln.split("#")[0].strip().strip("'") for ln in Path(args.from_file).read_text().splitlines() if ln.split("#")[0].strip()]
    done = _already_judged(getattr(args, "resume_from", None) or [])
    if done:
        before = len(specs)
        specs = [x for x in specs if x not in done]
        print(f"Resuming: {before - len(specs)} employers already judged in the earlier output are skipped; {len(specs)} left.", flush=True)
    cache = JobCache()
    throttle = Throttle()  # keeps a polite gap per website; each employer is its own website, so several can be read at once
    gate = asyncio.Semaphore(getattr(args, "parallel", 6))
    tally = {"added": 0, "skipped": 0}
    print(f"{len(specs)} employers to check. Rule: at least {args.min_jobs} jobs, mostly US or unclear, not a staffing agency. "
          f"{'WRITING to the saved lists.' if args.apply else 'Dry run: nothing is written.'}", flush=True)

    async def one(spec: str, client: Any) -> None:
        system, _, ident = spec.partition(":")
        async with gate:
            if args.apply:
                with cache.session() as db:
                    have = db.execute("SELECT 1 FROM employers WHERE ats = ? AND identifier = ?", (system, ident)).fetchone()
                if have:
                    print(f"  HAVE  {spec}  already in the saved lists", flush=True)
                    return
            res, err = None, ""
            for attempt in (1, 2, 3):  # a read that fails once (a busy site, a 504) often works a little later
                try:
                    res = await read_employer(system, ident, client, throttle)
                    break
                except Exception as exc:
                    err = f"{type(exc).__name__}: {str(exc)[:70]}".strip(": ")
                    if attempt < 3:
                        await asyncio.sleep(6 if attempt == 1 else 20)
            if res is None:
                tally["skipped"] += 1
                print(f"  SKIP  {spec}  could not be read ({err})", flush=True)
                return
            ok, why = add_decision(system, ident, res.postings, args)
            if not ok:
                tally["skipped"] += 1
                print(f"  SKIP  {spec}  {why}", flush=True)
                return
            if args.apply:
                eid, created = cache.upsert_employer(system, ident, res.name or "", args.source)
                if created:
                    cache.apply_refresh(eid, res.postings, now_ts(), 6.0, res.complete)
                    new_ids.append(eid)
                tally["added"] += 1
                print(f"  ADDED {spec}  {why}", flush=True)
            else:
                tally["added"] += 1
                print(f"  ADD   {spec}  {why}", flush=True)

    new_ids: list[int] = []
    async with make_client() as client:
        await asyncio.gather(*(one(s, client) for s in specs))
    print(f"\n{tally['added']} {'added' if args.apply else 'would be added'}, {tally['skipped']} skipped.", flush=True)
    if args.apply:
        from app.services.jobcache.industry import tag_employers

        with cache.session() as db:
            tag_employers(db)  # the new employers get an industry (employers that already have one are left alone)
        if new_ids:  # a first batch of descriptions comes in with each new employer
            from app.services.jobcache import service as _svc

            per = _svc.NEW_EMPLOYER_PER_EMPLOYER
            got = await _svc.fill_descriptions_gradually(cache, new_ids, per, per * len(new_ids))
            print(f"Saved {got} job descriptions from the new employers' postings (the rest fill in gradually).", flush=True)
        # employers whose lists stopped at Workday's old 2,000-job cutoff are read again so the rest of their jobs come in
        with cache.session() as db:
            capped = [r["id"] for r in db.execute(
                "SELECT e.id FROM employers e WHERE e.ats = 'workday' AND e.enabled = 1 AND "
                "(SELECT COUNT(*) FROM postings p WHERE p.employer_id = e.id AND p.closed_at IS NULL) = 2000")]
        if capped:
            from app.services.jobcache import service

            print(f"Reading {len(capped)} large Workday employer(s) again to pick up jobs past the old 2,000 cutoff ...", flush=True)
            print(service.run_refresh(only_ids=capped, limit=len(capped), seed=False), flush=True)
    return 0


_BOARD_HOSTS = {  # where each system's public job-board addresses live; "*.x.com" means every subdomain
    "greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io"),
    "lever": ("jobs.lever.co",),
    "ashby": ("jobs.ashbyhq.com",),
    "smartrecruiters": ("jobs.smartrecruiters.com",),
    "workable": ("apply.workable.com",),
    "jobvite": ("jobs.jobvite.com",),
    "bamboohr": ("*.bamboohr.com",),
    "breezy": ("*.breezy.hr",),
    "jazzhr": ("*.applytojob.com",),
    "pinpoint": ("*.pinpointhq.com",),
    "workday": ("*.myworkdayjobs.com",),  # the large employers: hospitals, health systems, banks, consultancies
    "icims": ("*.icims.com",),
    "taleo": ("*.taleo.net",),  # only addresses that carry the career site's org and cws are usable, so expect fewer
}


def parse_num_pages(text: str) -> int:
    """How many index pages Common Crawl says a search has. Accepts its JSON line, or a bare number; 0 when it says neither."""
    import json
    import re

    head = (text or "").strip().splitlines()[:1]
    if not head:
        return 0
    try:
        got = json.loads(head[0])
        if isinstance(got, dict):
            return int(got.get("pages", 0) or 0)
        if isinstance(got, int):
            return got
    except ValueError:
        pass
    m = re.search(r"pages\D{0,6}(\d+)", head[0], re.I) or re.fullmatch(r"\s*(\d+)\s*", head[0])
    return int(m.group(1)) if m else 0


def urls_from_cdx(text: str) -> tuple[list[str], int]:
    """Addresses in a Common Crawl answer (one JSON object per line). A line that is cut off or broken is skipped, not fatal; returns (addresses, lines skipped)."""
    import json

    urls: list[str] = []
    bad = 0
    for line in (text or "").splitlines():
        if not line.startswith("{"):
            continue
        try:
            urls.append(json.loads(line)["url"])
        except (ValueError, KeyError, TypeError):
            bad += 1
    return urls, bad


async def _cc_get(url: str, *, timeout: float, tries: int = 4):
    """Asks Common Crawl, waiting longer between tries when it says it is busy (HTTP 429/5xx) or the connection drops. Returns (response or None, note)."""
    from app.services.safe_fetch import safe_get

    note = ""
    for n in range(tries):
        try:
            r = await safe_get(url, timeout=timeout, max_bytes=12_000_000)
            if r.status_code == 200:
                return r, ""
            note = f"HTTP {r.status_code}"
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        except Exception as exc:
            note = type(exc).__name__
        await asyncio.sleep(4 * (2**n))
    return None, note


def boards_from_urls(urls: list[str], system: str, known: set[str]) -> list[str]:
    """Distinct employer boards named by these addresses on one hiring system, as 'system:name' lines, minus those already read."""
    from app.services.jobcache.readers import employer_ref

    have = {k.lower() for k in known}
    seen: dict[str, str] = {}
    for u in urls:
        ref = employer_ref(u)
        if ref and ref[0] == system and ref[1].lower() not in have:
            seen.setdefault(ref[1].lower(), f"{system}:{ref[1]}")
    return sorted(seen.values())


async def _discover(args: argparse.Namespace) -> int:
    """Asks Common Crawl for employer boards we do not read yet and writes them to a file for 'add' to check. Read only."""
    import json
    import random

    from app.services.safe_fetch import safe_get

    systems = sorted(_BOARD_HOSTS) if args.system == "all" else [s.strip() for s in args.system.split(",")]
    bad = [s for s in systems if s not in _BOARD_HOSTS]
    if bad:
        print(f"Not a system I can look for: {', '.join(bad)}. Choose from: {', '.join(sorted(_BOARD_HOSTS))}, or all.")
        return 1
    path = Path(args.db or settings.JOB_CACHE_PATH)
    try:
        info = json.loads((await safe_get("https://index.commoncrawl.org/collinfo.json", timeout=30)).text)
        api = info[0]["cdx-api"]
    except Exception as exc:
        print(f"Could not reach Common Crawl's index ({exc}). Nothing was changed.")
        return 1
    print(f"Using crawl {info[0].get('id')}.")
    rng = random.Random(args.seed)
    lines: list[str] = []
    before: set[str] = set()
    for prev in args.exclude or []:
        pp = Path(prev).expanduser()
        if pp.exists():
            before |= {ln.strip().strip("'") for ln in pp.read_text(encoding="utf-8").splitlines() if ln.strip()}
    for system in systems:
        known: set[str] = set()
        if path.exists():
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            known = {r[0] for r in con.execute("SELECT identifier FROM employers WHERE ats = ?", (system,))}
            con.close()
        urls: list[str] = []
        asked = failed = skipped = 0
        for host in _BOARD_HOSTS[system]:
            q = f"url={host[2:]}&matchType=domain" if host.startswith("*.") else f"url={host}/*"
            r, note = await _cc_get(f"{api}?{q}&output=json&showNumPages=true", timeout=60)
            pages = parse_num_pages(r.text) if r is not None else 0
            if r is None:
                print(f"  {system} {host}: could not ask ({note}); reading the first page only")
            elif not pages:
                print(f"  {system} {host}: no page count (answer began: {r.text[:80]!r}); reading the first page only")
            picks = rng.sample(range(pages), min(args.pages, pages)) if pages else [0]
            for pg in picks:
                asked += 1
                r, note = await _cc_get(f"{api}?{q}&output=json&fl=url&filter=status:200&page={pg}", timeout=120)
                if r is None:
                    failed += 1
                    print(f"    {system} page {pg}: gave up ({note})")
                else:
                    got, bad = urls_from_cdx(r.text)
                    urls += got
                    skipped += bad
                await asyncio.sleep(1.5)  # a polite gap between questions
        found = [b for b in boards_from_urls(urls, system, known) if b not in before]
        if args.limit:
            found = found[: args.limit]
        print(f"  {system}: {len(urls)} addresses seen, {len(found)} new boards ({len(known)} already read); questions {asked}, failed {failed}, broken lines skipped {skipped}")
        lines += [f"'{spec}'\n" for spec in found]
    Path(args.out).expanduser().write_text("".join(lines), encoding="utf-8")
    print(f"\n{len(lines)} new boards written to {args.out}. Nothing was added; check them with: cache_tools add --from-file {args.out}")
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


def cmd_industry(args: argparse.Namespace) -> int:
    from app.services.jobcache.industry import NAICS_CODES, tag_employers

    cache = JobCache()
    with cache.session() as db:
        table = tag_employers(db, retag=args.retag)
    total_e = sum(n for n, _ in table.values())
    total_j = sum(j for _, j in table.values()) or 1
    print("Industries are the US government's NAICS sectors (2022).")
    print(f"{'NAICS':6s} {'sector':56s} {'employers':>9s} {'open jobs':>10s} {'share':>7s}")
    for name, (n, jobs) in sorted(table.items(), key=lambda kv: -kv[1][1]):
        print(f"{NAICS_CODES.get(name, ''):6s} {name[:56]:56s} {n:9,d} {jobs:10,d} {100 * jobs / total_j:6.1f}%")
    print(f"{'':6s} {'ALL':56s} {total_e:9,d} {total_j:10,d}")
    return 0


def cmd_recheck(args: argparse.Namespace) -> int:
    """Reads the named hiring system's employers again now (used after a reader fix), so saved jobs get the corrected details."""
    from app.services.jobcache import service

    cache = JobCache()
    with cache.session() as db:
        ids = [r["id"] for r in db.execute("SELECT id FROM employers WHERE enabled = 1 AND ats = ?", (args.system,))]
    if not ids:
        print(f"No enabled employers on {args.system}.")
        return 0
    print(f"Reading {len(ids)} {args.system} employers again ...", flush=True)
    print(service.run_refresh(only_ids=ids, limit=len(ids), seed=False), flush=True)
    return 0


_GENERIC_NAMES = {"careers", "career", "jobs", "job search", "search", "home", "search results", "career opportunities", "external", "login", "sign in", "workday", "icims", "jobvite", "bamboohr"}
_NAME_TRAIL = re.compile(r"\s*[-|:\u2013\u2014]\s*(careers?|jobs?|job search|job openings|current openings|career opportunities|employment|join us|work with us)\b.*$|\s+(careers?|jobs?|job search|career site|career opportunities)$", re.I)
_JOB_PREFIX = re.compile(r"^(careers?|jobs?|job search|search jobs|search results)\s*(at|[-|:\u2013\u2014])\s*", re.I)


def clean_found_name(raw: str | None) -> str | None:
    """A company name out of a page title ("KidsCare Home Health - Careers" -> "KidsCare Home Health"), or None when it is not a usable name."""
    import html as _html

    name = re.sub(r"\s+", " ", _html.unescape(raw or "")).strip()
    name = _JOB_PREFIX.sub("", name)
    name = _NAME_TRAIL.sub("", name).strip(" -|:,")
    if not (2 <= len(name) <= 60) or name.lower() in _GENERIC_NAMES or re.search(r"\b(search|openings?|apply|login|sign in|404|not found|error)\b", name, re.I):
        return None
    return name


def _home_page(ats: str, identifier: str) -> str | None:
    """The employer's own public careers page, where its name is usually the page title."""
    if ats == "icims":
        return f"https://{identifier}/jobs/search?ss=1&in_iframe=1"
    if ats == "workday" and identifier.count("|") == 2:
        host, _tenant, site = identifier.split("|")
        return f"https://{host}/{site}"
    if ats == "bamboohr":
        return f"https://{identifier}.bamboohr.com/careers"
    if ats == "jobvite":
        return f"https://jobs.jobvite.com/{identifier}/jobs"
    return None


async def _find_name(emp: dict, row_url: str | None) -> tuple[str | None, str]:
    """(a name, where it came from). Tries the structured data of one of its job pages first, then the careers page's own title."""
    from app.services.discovery import manual_extraction as mx
    from app.services.jobcache.service import _description_request
    from app.services.safe_fetch import safe_get

    async def page(url: str) -> str | None:
        try:
            resp = await safe_get(url, headers={"User-Agent": mx._USER_AGENT, "Accept": "text/html"}, timeout=8.0)
        except Exception:
            return None
        return resp.text[:400000] if resp.status_code == 200 else None

    if row_url:
        req = _description_request(row_url)
        body = await page(req[1] if req and req[0] == "icims" else row_url)
        for block in mx._JSONLD_PATTERN.findall(body or ""):
            try:
                data = json.loads(block)
            except (ValueError, TypeError):
                continue
            for item in mx._flatten_jsonld(data):
                org = item.get("hiringOrganization") if isinstance(item, dict) else None
                found = clean_found_name(org.get("name") if isinstance(org, dict) else org if isinstance(org, str) else None)
                if found:
                    return found, "job page data"
    home = _home_page(emp["ats"], emp["identifier"])
    body = await page(home) if home else None
    if body:
        for pattern, label in ((r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', "site name"), (r"<title[^>]*>([^<]+)</title>", "page title")):
            m = re.search(pattern, body, re.I)
            found = clean_found_name(m.group(1)) if m else None
            if found:
                return found, label
    return None, ""


async def _names_find(args: argparse.Namespace) -> int:
    from app.services.jobcache.store import guess_name
    from app.services.jobcache.text import clean_company

    cache = JobCache()
    with cache.session() as db:
        emps = [dict(r) for r in db.execute("SELECT id, ats, identifier, name, open_count FROM employers WHERE enabled = 1")]
    guessed = [e for e in emps if e["name"] == guess_name(e["ats"], e["identifier"]) and " " not in clean_company(e["name"]) and len(e["name"]) >= 7]
    guessed.sort(key=lambda e: -(e["open_count"] or 0))
    guessed = guessed[: args.limit]
    print(f"Looking up the real names of {len(guessed)} employers (reads each employer's own public careers pages) ...", flush=True)
    gate = asyncio.Semaphore(4)
    out: list[dict] = []

    async def one(e: dict) -> None:
        async with gate:
            with cache.session() as db:
                r = db.execute("SELECT url FROM postings WHERE employer_id = ? AND closed_at IS NULL LIMIT 1", (e["id"],)).fetchone()
            name, source = await _find_name(e, r["url"] if r else None)
            await asyncio.sleep(0.7)
        out.append({"system": e["ats"], "identifier": e["identifier"], "open_jobs": e["open_count"], "current_name": e["name"], "new_name": name or "", "found_in": source})

    await asyncio.gather(*(one(e) for e in guessed))
    out.sort(key=lambda r: -(r["open_jobs"] or 0))
    path = Path(args.out).expanduser()
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["system", "identifier", "open_jobs", "current_name", "new_name", "found_in"])
        w.writeheader()
        w.writerows(out)
    found = sum(1 for r in out if r["new_name"])
    print(f"Found a name for {found} of {len(out)}. Nothing has been changed yet. Review: {path}")
    return 0


def cmd_names_apply(args: argparse.Namespace) -> int:
    """Writes the reviewed names from the file into the employer list (only rows with a new_name; a blank new_name changes nothing)."""
    cache = JobCache()
    changed = 0
    with Path(args.apply).expanduser().open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    with cache.session() as db:
        for r in rows:
            new = (r.get("new_name") or "").strip()
            if new and new != r["current_name"]:
                cur = db.execute("UPDATE employers SET name = ? WHERE ats = ? AND identifier = ?", (new, r["system"], r["identifier"]))
                changed += cur.rowcount
    print(f"Renamed {changed} employers.")
    return 0


def cmd_names(args: argparse.Namespace) -> int:
    """Employers whose name is still only a guess from the web address. `--find` looks the real names up and writes a file to review; `--apply FILE` saves the reviewed file."""
    if args.apply:
        return cmd_names_apply(args)
    if args.find:
        return asyncio.run(_names_find(args))
    from app.services.jobcache.store import guess_name
    from app.services.jobcache.text import clean_company

    cache = JobCache()
    with cache.session() as db:
        rows = [dict(r) for r in db.execute("SELECT ats, identifier, name, open_count FROM employers WHERE enabled = 1")]
    guessed = [r for r in rows if r["name"] == guess_name(r["ats"], r["identifier"]) and " " not in clean_company(r["name"]) and len(r["name"]) >= 7]
    by: dict[str, int] = {}
    for r in guessed:
        by[r["ats"]] = by.get(r["ats"], 0) + 1
    print(f"{len(guessed)} of {len(rows)} employers still have a one-word guessed name:")
    for ats, n in sorted(by.items(), key=lambda kv: -kv[1]):
        print(f"  {ats:16s} {n}")
    print("Biggest examples:")
    for r in sorted(guessed, key=lambda r: -(r["open_count"] or 0))[: args.limit]:
        print(f"  {r['name']:30s} {r['ats']:16s} {r['open_count']} open")
    return 0


US_OFF_NOTE = "turned off: mostly outside the US"


def cmd_usshare(args: argparse.Namespace) -> int:
    """Lists employers whose open jobs are mostly outside the US (by the same place reading the add rule uses). --disable turns them off."""
    cache = JobCache()
    if args.restore:
        with cache.session() as db:
            n = db.execute("UPDATE employers SET enabled = 1, last_error = NULL WHERE enabled = 0 AND last_error = ?", (US_OFF_NOTE,)).rowcount
        print(f"Turned {n} employers back on.")
        return 0
    counts: dict[int, list[int]] = {}  # employer id -> [jobs, clearly US, clearly foreign]
    info: dict[int, tuple[str, str]] = {}
    with cache.session() as db:
        for r in db.execute(
            "SELECT e.id, e.name, e.ats, p.location FROM postings p JOIN employers e ON e.id = p.employer_id WHERE p.closed_at IS NULL AND e.enabled = 1"
        ):
            c = counts.setdefault(r["id"], [0, 0, 0])
            info[r["id"]] = (r["name"], r["ats"])
            kind = location_kind(r["location"])
            c[0] += 1
            c[1] += kind == "us"
            c[2] += kind == "foreign"
    jobs_all = sum(c[0] for c in counts.values())
    us_all = sum(c[1] for c in counts.values())
    foreign_all = sum(c[2] for c in counts.values())
    print(f"All enabled employers: {len(counts):,} employers, {jobs_all:,} jobs; {100 * us_all // max(jobs_all, 1)}% clearly US, {100 * foreign_all // max(jobs_all, 1)}% clearly outside the US.")
    flagged = sorted(
        (i for i, c in counts.items() if c[0] >= 1 and 100 * c[1] // c[0] < args.max_us and 100 * c[2] // c[0] >= args.min_foreign and c[1] < args.keep_us_jobs),
        key=lambda i: -counts[i][0],
    )
    jobs_flagged = sum(counts[i][0] for i in flagged)
    print(f"\nMostly outside the US (under {args.max_us}% US, at least {args.min_foreign}% outside, and fewer than {args.keep_us_jobs} US jobs): {len(flagged):,} employers, {jobs_flagged:,} jobs.")
    for i in flagged[: args.top]:
        c = counts[i]
        print(f"  {info[i][0][:40]:40s} {info[i][1]:16s} {c[0]:6,d} jobs  US {100 * c[1] // c[0]:3d}%  outside {100 * c[2] // c[0]:3d}%")
    if args.disable and flagged:
        with cache.session() as db:
            db.executemany("UPDATE employers SET enabled = 0, last_error = ? WHERE id = ?", [(US_OFF_NOTE, i) for i in flagged])
        print(f"\nTurned off {len(flagged):,} employers. Nothing was deleted. Undo with: cache_tools usshare --restore")
    elif flagged:
        print("\nDry run: nothing changed. Add --disable to turn these employers off (reversible).")
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    cache = JobCache(args.db) if args.db else JobCache()
    if not cache.has_desc:
        print("This copy of SQLite has no full-text search, so descriptions cannot be indexed. Nothing was changed.")
        return 1
    print(f"Indexing the opening lines of job descriptions in {cache.path} ...", flush=True)
    n = cache.reindex_descriptions(progress=lambda done: print(f"  {done:,} postings indexed", flush=True) if done % 10000 < 2000 else None)
    print(f"Done: {n:,} postings added to the description index. Search now reads descriptions (switch off with JOB_SEARCH_USE_DESCRIPTION=false).")
    return 0


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)  # show each line as it happens, even when piped to a file or tee
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("coverage")
    c.add_argument("--db")
    d = sub.add_parser("descriptions")
    d.add_argument("--db")
    d.add_argument("--title", help="only postings whose title holds these words, e.g. 'revenue cycle'")
    f = sub.add_parser("fill")
    f.add_argument("--limit", type=int, default=150, help="postings to read in this batch")
    f.add_argument("--system", help="only these hiring systems, e.g. workday,icims,smartrecruiters")
    f.add_argument("--rounds", type=int, default=1, help="how many batches to run in a row (for an overnight catch-up)")
    f.add_argument("--per-employer", type=int, default=15, help="most postings read from one employer per batch")
    f.add_argument("--pause", type=float, default=2.0, help="seconds to wait between batches")
    f.add_argument("--retry", help="comma separated hiring systems whose unreadable postings should be tried again, e.g. icims,smartrecruiters,workable")
    nm = sub.add_parser("names")
    nm.add_argument("--limit", type=int, default=25)
    nm.add_argument("--find", action="store_true", help="look the real names up and write a file to review (changes nothing)")
    nm.add_argument("--out", default="~/Desktop/employer-names.csv")
    nm.add_argument("--apply", help="save the names in this reviewed file")
    r = sub.add_parser("reread")
    r.add_argument("--db", required=True)
    r.add_argument("--only", help="comma separated hiring systems, e.g. greenhouse,lever,ashby")
    r.add_argument("--live", action="store_true")
    s = sub.add_parser("sites")
    s.add_argument("--db")
    s.add_argument("--max-hosts", type=int, default=60)
    dc = sub.add_parser("discover")
    dc.add_argument("--system", required=True, help="greenhouse, lever, ashby, smartrecruiters, workable, jobvite, bamboohr, breezy, jazzhr, pinpoint, workday, icims, taleo (comma separated) or all")
    dc.add_argument("--db")
    dc.add_argument("--pages", type=int, default=6, help="random index pages to read per address")
    dc.add_argument("--limit", type=int, default=300, help="most boards to write per hiring system (0 = no limit)")
    dc.add_argument("--exclude", action="append", help="a file from an earlier discover run; boards in it are left out so each run finds new ones (repeatable)")
    dc.add_argument("--seed", type=int, default=1)
    dc.add_argument("--out", default="/tmp/discovered.txt")
    ad = sub.add_parser("add")
    ad.add_argument("--from-file", required=True)
    ad.add_argument("--apply", action="store_true", help="actually add them (without this it only shows what it would do)")
    ad.add_argument("--min-jobs", type=int, default=10)
    ad.add_argument("--min-us", type=int, default=60)
    ad.add_argument("--keep-us-jobs", type=int, default=15, help="an employer with at least this many clearly US jobs passes the place check even when it is mostly abroad (default 15)")
    ad.add_argument("--include", action="append", help="add any employer whose address contains this text without the place check (repeatable)")
    ad.add_argument("--resume-from", action="append", metavar="FILE", help="an earlier output of this command; employers already judged there are not checked again (repeatable)")
    ad.add_argument("--skip", action="append", help="leave out any employer whose address contains this text (repeatable)")
    ad.add_argument("--source", default="curated")
    ad.add_argument("--parallel", type=int, default=6, help="employers read at the same time (each is a different website)")
    rc = sub.add_parser("recheck")
    rc.add_argument("--system", required=True, help="hiring system to read again, e.g. smartrecruiters")
    us = sub.add_parser("usshare")
    us.add_argument("--max-us", type=int, default=30, help="employers with a smaller share of clearly US jobs than this are listed")
    us.add_argument("--min-foreign", type=int, default=50, help="and at least this share clearly outside the US")
    us.add_argument("--keep-us-jobs", type=int, default=15, help="never list an employer that still has at least this many clearly US jobs (default 15)")
    us.add_argument("--top", type=int, default=40)
    us.add_argument("--disable", action="store_true", help="turn the listed employers off (they stay saved, and --restore turns them back on)")
    us.add_argument("--restore", action="store_true", help="turn back on the employers this command turned off")
    ri = sub.add_parser("reindex")
    ri.add_argument("--db", help="another copy of the saved lists, such as the frozen test copy (default: the live one)")
    ind = sub.add_parser("industry")
    ind.add_argument("--retag", action="store_true", help="redo every employer, not only the ones with no industry yet")
    pr = sub.add_parser("probe")
    pr.add_argument("--from-file", help="a file of specs, one per line (what 'eval_search gaps --write-probes' writes)")
    pr.add_argument("employers", nargs="*", help="system:identifier, e.g. 'workday:bilh.wd1.myworkdayjobs.com|bilh|external'")
    pr.add_argument("--samples", type=int, default=8, help="(no longer used)")
    pr.add_argument("--out", help="also save the table to this file")
    args = p.parse_args()
    if args.cmd == "discover":
        sys.exit(asyncio.run(_discover(args)))
    if args.cmd == "add":
        sys.exit(asyncio.run(_add(args)))
    if args.cmd == "recheck":
        sys.exit(cmd_recheck(args))
    if args.cmd == "usshare":
        sys.exit(cmd_usshare(args))
    if args.cmd == "descriptions":
        sys.exit(cmd_descriptions(args))
    if args.cmd == "fill":
        sys.exit(asyncio.run(_fill(args)))
    if args.cmd == "reindex":
        sys.exit(cmd_reindex(args))
    if args.cmd == "names":
        sys.exit(cmd_names(args))
    if args.cmd == "industry":
        sys.exit(cmd_industry(args))
    if args.cmd == "probe":
        sys.exit(asyncio.run(_probe(args)))
    if args.cmd == "sites":
        sys.exit(asyncio.run(_sites(args)))
    sys.exit(cmd_coverage(args) if args.cmd == "coverage" else asyncio.run(_reread(args)))


if __name__ == "__main__":
    main()
