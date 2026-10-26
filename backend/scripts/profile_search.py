"""
Times a few searches on the saved job lists and shows where the time goes. Read only: nothing is written.

  python -m scripts.profile_search [--db PATH]
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import time
from types import SimpleNamespace

SEARCHES = [
    ("data analyst", "Boston, MA"),
    ("revenue cycle manager", "Boston, MA"),
    ("management consultant", "Boston, MA"),
    ("software engineer", "United States"),
    ("project manager", "Orlando, FL"),
]


def criteria(title: str, place: str) -> SimpleNamespace:
    return SimpleNamespace(titles=title, location=place, work_type="any", keywords=None, target_salary=None, require_salary=False,
                           posted_within_days=0, exclude_companies=None, count=10)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="a job cache file (default: the app's own)")
    args = ap.parse_args()
    from app.services.jobcache import service
    from app.services.jobcache.store import JobCache

    if args.db:
        service.JobCache = lambda *a, **k: JobCache(args.db)  # type: ignore[assignment]
    print(f"{'search':44} {'seconds':>8} {'candidates':>11} {'results':>8}")
    for title, place in SEARCHES:
        c = criteria(title, place)
        t0 = time.perf_counter()
        out = service.search_sync(c, set(), None, 15)
        dt = time.perf_counter() - t0
        print(f"{title + ' / ' + place:44} {dt:8.2f} {'':>11} {len(out.items):8}")
    prof = cProfile.Profile()
    c = criteria("management consultant", "Boston, MA")
    prof.enable()
    service.search_sync(c, set(), None, 15)
    prof.disable()
    buf = io.StringIO()
    pstats.Stats(prof, stream=buf).sort_stats("cumulative").print_stats(22)
    print("\nWhere the time goes (management consultant / Boston, MA):")
    print(buf.getvalue()[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
