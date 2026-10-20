"""
Times each step of a saved-list search (the core search, then the checks that follow it). Uses the frozen test copy and writes nothing.

  python -m scripts.profile_stages [--count 3]
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections import defaultdict

from scripts import eval_search as ev
from app.services.discovery import web_search as ws
from app.services.jobcache import service as cache_service

STEPS = ["rerank_items", "resolve_original_sources", "upgrade_to_ats_links", "enrich_from_ats", "fill_posted_dates", "drop_closed"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=3)
    args = ap.parse_args()
    ev.use_frozen()
    spent: dict[str, float] = defaultdict(float)

    def wrap(owner, name: str):
        fn = getattr(owner, name)

        async def timed(*a, **k):
            t0 = time.perf_counter()
            try:
                return await fn(*a, **k)
            finally:
                spent[name] += time.perf_counter() - t0

        setattr(owner, name, timed)

    for name in STEPS:
        wrap(ws, name)
    wrap(cache_service, "search_cache")
    wrap(cache_service, "expand_titles")

    searches = ev.evalset.load_searches()[: args.count]

    async def go() -> None:
        for s in searches:
            spent.clear()
            t0 = time.perf_counter()
            out = await ws.search_jobs_full(s["criteria"], set(), cache_only=True)
            total = time.perf_counter() - t0
            print(f"\n{s['id']}: {total:.1f}s total, {len(out.items)} results")
            for k, v in sorted(spent.items(), key=lambda kv: -kv[1]):
                print(f"   {k:28} {v:6.2f}s")

    asyncio.run(go())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
