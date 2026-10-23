"""
Before-and-after check for the stricter ranking. Reads your saved job lists only; nothing is saved or changed.

  cd backend && python -m scripts.score_ab
  cd backend && python -m scripts.score_ab --titles "revenue cycle manager" --location "New York, NY"

For each search it prints the top results with today's ranking (OLD) and the stricter one (NEW), then a summary:
how many are in the city, remote, or elsewhere, how many are over 60 days old, and the spread of fit tiers.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections import Counter

from app.schemas.job_search import JobSearchIn
from app.services.jobcache import matcher, service
from app.services.jobcache.text import parse_location_query

SEARCHES = [
    JobSearchIn(titles="revenue cycle manager", location="Boston, MA"),
    JobSearchIn(titles="revenue cycle manager", location="New York, NY"),
    JobSearchIn(titles="revenue cycle analyst", location="Boston, MA"),
    JobSearchIn(titles="project manager", location="Orlando, FL"),
]


def tier(fit: float) -> str:
    n = fit * 100
    return "Top" if n >= 90 else "Strong" if n >= 75 else "Good" if n >= 55 else "Possible"


def where(item: dict, city: str | None) -> str:
    loc = (item.get("location") or "").lower()
    if item.get("work_type") == "remote" or "remote" in loc:
        return "remote"
    return "city" if city and city in loc else "elsewhere"


def run(criteria: JobSearchIn, strict: bool, top: int):
    matcher.STRICT_OVERRIDE = strict
    try:
        return service.search_sync(criteria, set(), None, 60)
    finally:
        matcher.STRICT_OVERRIDE = None


def show(label: str, outcome, criteria: JobSearchIn, top: int) -> None:
    loc = parse_location_query(criteria.location)
    city = next(iter(loc.cities), None)
    city = city.lower() if city else None
    items = outcome.items[:top]
    today = dt.date.today()
    print(f"  {label}: {outcome.matches} matches")
    for i in items:
        age = (today - i["posted_at"]).days if i.get("posted_at") else None
        print(f"    {round(i['fit'] * 100):>3} {tier(i['fit']):<8} {where(i, city):<9} {str(age) + 'd' if age is not None else '?':>5}  {i['title'][:48]} | {i['company'][:22]} | {(i.get('location') or '')[:26]}")
    spots = Counter(where(i, city) for i in items)
    old = sum(1 for i in items if i.get("posted_at") and (today - i["posted_at"]).days > 60)
    tiers = Counter(tier(i["fit"]) for i in items)
    print(f"    top {len(items)}: {dict(spots)}; over 60 days old: {old}; tiers: {dict(tiers)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--titles")
    ap.add_argument("--location")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()
    searches = [JobSearchIn(titles=args.titles, location=args.location)] if args.titles else SEARCHES
    for c in searches:
        print(f"\n=== {c.titles} | {c.location}")
        show("OLD", run(c, False, args.top), c, args.top)
        show("NEW", run(c, True, args.top), c, args.top)


if __name__ == "__main__":
    main()
