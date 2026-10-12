"""
Search experiment: three ways of doing the web part of a job search, on the same criteria and the same finishing checks.

  A  today: two web calls (hiring systems, then company sites)
  B  one web call over everything except job boards
  C  one web call over the job boards (Indeed, LinkedIn...), then each result is traced to the employer's own link

It only reads: nothing is saved to your job database or the job cache. It spends real money on the AI search
(a few cents per search per mode) and stops when --max-spend would be passed. Run with --dry-run first.

  cd backend && python -m scripts.search_ab --dry-run
  cd backend && python -m scripts.search_ab --models anthropic/claude-haiku-5.5,openai/gpt-4o-mini
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.schemas.job_search import JobSearchIn
from app.services.discovery import web_search as ws
from app.services.jobcache import matcher
from app.services.llm.client import LLMClient

SEARCH_FEE = 0.007  # dollars per web search (Exa through OpenRouter, about $7 per 1,000)
# dollars per million tokens (input, output), OpenRouter list prices; unknown models count the search fee only
PRICES = {
    "anthropic/claude-haiku-5.5": (0.10, 0.50),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "deepseek/deepseek-chat": (0.32, 0.89),
    "z-ai/glm-5.3-flash": (0.15, 0.50),
    "openai/gpt-6-luna": (0.10, 0.50),
}
BOARDS = ["linkedin.com", "indeed.com", "ziprecruiter.com", "glassdoor.com", "simplyhired.com", "monster.com", "careerbuilder.com", "dice.com"]
MODES = ["A", "B", "C"]
CALLS_PER_SEARCH = {"A": 2, "B": 1, "C": 1 + 8}  # C: one board search plus up to 8 lookups for the employer's link
DEFAULT_SEARCHES = [
    JobSearchIn(titles="revenue cycle manager, revenue cycle analyst", location="Boston, MA", posted_within_days=30, count=10),
    JobSearchIn(titles="project manager", location="Orlando, FL", posted_within_days=30, count=10),
    JobSearchIn(titles="revenue cycle analyst", location="United States", work_type="remote", posted_within_days=30, count=10),
]


NO_REASONING = False  # set by --no-reasoning: asks the model not to "think" before answering


class Meter:
    """Counts every AI call (tokens and web searches) by wrapping the real client."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.real = LLMClient.chat_completion

    def install(self) -> None:
        meter = self

        async def wrapped(self_client, **kw):  # type: ignore[no-untyped-def]
            t0 = time.time()
            if NO_REASONING:
                kw["extra"] = {**(kw.get("extra") or {}), "reasoning": {"enabled": False}}
            result = await meter.real(self_client, **kw)
            plugins = (kw.get("extra") or {}).get("plugins") or []
            meter.calls.append(
                {
                    "model": kw.get("model"),
                    "in": result.input_tokens,
                    "out": result.output_tokens,
                    "web": 1 if any(p.get("id") == "web" for p in plugins) else 0,
                    "secs": round(time.time() - t0, 1),
                    "cost": (result.raw.get("usage") or {}).get("cost") if isinstance(result.raw, dict) else None,
                    "empty": 0 if (result.content or "").strip() else 1,
                    "stop": ((result.raw.get("choices") or [{}])[0].get("finish_reason")) if isinstance(result.raw, dict) else None,
                }
            )
            return result

        LLMClient.chat_completion = wrapped  # type: ignore[method-assign]

    def cost(self, model: str, since: int = 0) -> float:
        pin, pout = PRICES.get(model, (0.0, 0.0))
        return sum(c["web"] * SEARCH_FEE + c["in"] * pin / 1e6 + c["out"] * pout / 1e6 for c in self.calls[since:])


def max_cost(model: str) -> float:
    """Worst case for one search in one mode, from the call counts and a generous token estimate per call."""
    pin, pout = PRICES.get(model, (0.15, 0.60))
    per_call = SEARCH_FEE + 4000 * pin / 1e6 + 1000 * pout / 1e6
    return sum(per_call * n for n in CALLS_PER_SEARCH.values())


async def one_call(criteria: JobSearchIn, model: str, *, include: list[str] | None, exclude: list[str] | None, system: str, count: int) -> list[dict[str, Any]]:
    plugin = ws.web_plugin(max(5, min(count + 2, 10)))
    if include:
        plugin["include_domains"] = include
    if exclude:
        plugin["exclude_domains"] = exclude
    msgs = ws.build_messages(criteria, "web")
    msgs[0] = {"role": "system", "content": system}
    msgs[1] = {"role": "user", "content": msgs[1]["content"].replace(f"up to {ws.per_call_count(criteria, 'web')}", f"up to {count}")}
    result = await LLMClient().chat_completion(model=model, messages=msgs, temperature=0.0, max_tokens=2500, extra={"plugins": [plugin]}, timeout=150.0)
    return ws._clean_items(ws.parse_items(result.content), criteria, ws.cited_urls(result.raw), {})


def system_for(mode: str, criteria: JobSearchIn) -> str:
    base = ws.build_messages(criteria, "web")[0]["content"]
    if mode == "B":
        return base.replace(ws.SCOPES["web"]["hint"], "Search company career sites and applicant-tracking pages (Workday, Greenhouse, Ashby, Lever, iCIMS and the like).")
    # C: job boards are the point, so the "never a job board" rule is replaced
    start = base.index("Use the employer's own career site")
    end = base.index("The title must be")
    return base[:start] + "Search job boards such as LinkedIn and Indeed for current postings. " + base[end:].replace(ws.SCOPES["web"]["hint"], "Report the posting page on the board.")


async def raw_candidates(mode: str, criteria: JobSearchIn, model: str) -> list[dict[str, Any]]:
    if mode == "A":
        outs = await asyncio.gather(*(ws._search_one(criteria, s, model) for s in ws.SCOPES), return_exceptions=True)
        return [i for o in outs if isinstance(o, list) for i in o]
    count = ws.per_call_count(criteria, "ats")
    if mode == "B":
        return await one_call(criteria, model, include=None, exclude=sorted(ws.AGGREGATOR_DOMAINS), system=system_for("B", criteria), count=count)
    return await one_call(criteria, model, include=BOARDS, exclude=None, system=system_for("C", criteria), count=count)


async def finish(items: list[dict[str, Any]], criteria: JobSearchIn) -> list[dict[str, Any]]:
    """The same checks every real search ends with, so the modes are compared on what the user would see."""
    ws.tidy_items(items)
    plan = matcher.build_plan(criteria, [])
    items = [i for i in items if matcher.title_fit(plan, i["title"]) >= matcher.MIN_TITLE_FIT]
    items = ws._dedupe_by_address(items)
    items = ws.merge_same_jobs(items)
    items = ws.merge_twin_postings(items)
    items, _ = await ws.resolve_original_sources(items)
    items = await ws.upgrade_to_ats_links(items)
    items, _ = await ws.enrich_from_ats(items)
    items, _ = await ws.fill_posted_dates(items, criteria.posted_within_days, need_pay=criteria.require_salary)
    items, _ = ws.apply_pay_rules(items, criteria)
    kept, _ = await ws.drop_closed(items)
    return kept[: criteria.count]


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def measure(items: list[dict[str, Any]], criteria: JobSearchIn) -> dict[str, Any]:
    today = dt.date.today()
    fresh = [i for i in items if i.get("posted_at") and (not criteria.posted_within_days or (today - i["posted_at"]).days <= criteria.posted_within_days)]
    return {
        "results": len(items),
        "employer_direct": sum(1 for i in items if not ws.is_aggregator(i["url"]) and not ws.is_board_url(i["url"], i["company"])),
        "readable_ats": sum(1 for i in items if host(i["url"]).endswith(ws.ATS_SUFFIXES_KNOWN)),
        "confirmed_open": sum(1 for i in items if i.get("ats_checked") and i.get("ats_live")),
        "dated_in_window": len(fresh),
    }


async def run(args: argparse.Namespace) -> int:
    searches = DEFAULT_SEARCHES
    if args.searches:
        searches = [JobSearchIn(**s) for s in json.loads(Path(args.searches).read_text())]
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    modes = [m for m in args.modes.upper().split(",") if m in MODES]
    worst = sum(max_cost(m) for m in models) * len(searches) * len(modes) / len(MODES)
    print(f"Plan: {len(searches)} searches x {len(modes)} modes ({','.join(modes)}) x {len(models)} models = {len(searches) * len(modes) * len(models)} runs")
    for s in searches:
        print(f"  - {s.titles} | {s.location} | {s.work_type} | last {s.posted_within_days or 'any'} days")
    for m in models:
        print(f"  model {m}: {'priced' if m in PRICES else 'NOT in price table, only the search fee is counted'}")
    print(f"Worst-case spend about ${worst:.2f}; stops at ${args.max_spend:.2f}. Nothing is saved to your database.")
    if args.dry_run:
        print("Dry run: no AI calls made.")
        return 0

    global NO_REASONING
    NO_REASONING = bool(getattr(args, "no_reasoning", False))
    print("Reasoning: " + ("switched off for every call" if NO_REASONING else "model default"))
    spent = 0.0
    meter = Meter()
    meter.install()
    ok_models = []
    for model in models:  # one tiny call per model (a fraction of a cent) so a wrong name or setting fails before the real runs
        try:
            r = await LLMClient().chat_completion(model=model, messages=[{"role": "user", "content": "Reply with the single word OK."}], max_tokens=400, timeout=60.0)
            spent += meter.cost(model, len(meter.calls) - 1)
            if r.content.strip():
                print(f"  check {model}: ok")
            else:
                print(f"  check {model}: answered with nothing (its thinking may use the whole answer budget); continuing")
            ok_models.append(model)
        except Exception as exc:
            print(f"  check {model}: FAILED ({type(exc).__name__}: {str(exc)[:200]}); this model is skipped, nothing more is spent on it")
    models = ok_models
    if not models:
        print("No model passed the check. Nothing was run.")
        return 1
    rows: list[dict[str, Any]] = []
    seen: dict[tuple[int, str], set[str]] = {}
    for si, criteria in enumerate(searches):
        for model in models:
            ws.search_model = lambda m=model: m  # type: ignore[assignment]
            for mode in modes:
                if spent >= args.max_spend:
                    print(f"Stopped: reached the ${args.max_spend:.2f} limit.")
                    break
                start = len(meter.calls)
                t0 = time.time()
                err = ""
                items: list[dict[str, Any]] = []
                try:
                    raw = await raw_candidates(mode, criteria, model)
                    raw_n = len(raw)
                    items = await finish(raw, criteria)
                except Exception as exc:  # one failed run should not lose the others
                    raw_n, err = 0, f"{type(exc).__name__}: {exc}"[:120]
                    where = traceback.format_exc().strip().splitlines()[-5:-1]
                    print("    where it failed:", " | ".join(w.strip() for w in where))
                    err += " @ " + where[0].strip()[:160] if where else ""
                cost = meter.cost(model, start)
                spent += cost
                calls = meter.calls[start:]
                row = {
                    "search": f"{criteria.titles.split(',')[0]} / {criteria.location}",
                    "model": model,
                    "mode": mode,
                    "raw_from_ai": raw_n,
                    **measure(items, criteria),
                    "ai_calls": len(calls),
                    "web_searches": sum(c["web"] for c in calls),
                    "tokens_in": sum(c["in"] for c in calls),
                    "tokens_out": sum(c["out"] for c in calls),
                    "empty_replies": sum(c["empty"] for c in calls),
                    "stop_reasons": "/".join(sorted({str(c["stop"]) for c in calls})),
                    "est_cost_usd": round(cost, 4),
                    "billed_usd": round(sum(c["cost"] for c in calls), 4) if calls and all(c.get("cost") is not None for c in calls) else "n/a",
                    "seconds": round(time.time() - t0, 1),
                    "error": err,
                    "_urls": [(i["title"], i["company"], i["url"]) for i in items],
                }
                seen[(si, f"{model}|{mode}")] = {k for i in items for k in ws.loose_keys(i["url"])}
                rows.append(row)
                print(f"  {row['search'][:40]:40} {model.split('/')[-1][:18]:18} {mode}: {row['results']} results, {row['employer_direct']} direct, ${cost:.3f} {err}")
    # results only found by one mode, per search and model
    for row in rows:
        si = next(i for i, c in enumerate(searches) if f"{c.titles.split(',')[0]} / {c.location}" == row["search"])
        mine = seen[(si, f"{row['model']}|{row['mode']}")]
        others = set().union(*(v for (s, k), v in seen.items() if s == si and k.startswith(row["model"] + "|") and k != f"{row['model']}|{row['mode']}"))
        row["only_this_mode"] = sum(1 for _, _, u in row["_urls"] if not (ws.loose_keys(u) & others))
        del mine

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    cols = [k for k in rows[0] if not k.startswith("_")] if rows else []
    with open(out / f"search_ab-{stamp}{'-noreason' if NO_REASONING else ''}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    lines = [f"# Search experiment {stamp}", f"Estimated spend ${spent:.2f} (compare with the OpenRouter Logs page)", ""]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "---|" * len(cols))
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    for r in rows:
        lines += ["", f"## {r['search']} | {r['model']} | mode {r['mode']}"] + [f"- {t} at {c}: {u}" for t, c, u in r["_urls"]]
    (out / f"search_ab-{stamp}{'-noreason' if NO_REASONING else ''}.md").write_text("\n".join(lines))
    print(f"\nEstimated total ${spent:.2f}. Report: {out / f'search_ab-{stamp}{chr(45)}noreason.md' if NO_REASONING else out / f'search_ab-{stamp}.md'}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", default="anthropic/claude-haiku-5.5,openai/gpt-4o-mini")
    p.add_argument("--modes", default="A,B,C")
    p.add_argument("--searches", help="JSON file with a list of search criteria (same fields as the Job Search form)")
    p.add_argument("--max-spend", type=float, default=1.0)
    p.add_argument("--out", default=str(Path.home() / "Desktop" / "job-agent-experiments"))
    p.add_argument("--no-reasoning", action="store_true", help="ask the model to answer without a thinking step")
    p.add_argument("--dry-run", action="store_true")
    sys.exit(asyncio.run(run(p.parse_args())))


if __name__ == "__main__":
    main()
