"""The search quality test set: searches, pool, labels, scoring, the review screen and the script. No network, no AI."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from types import SimpleNamespace

import pytest

from app.config import settings
from app.schemas.job_search import JobSearchIn
from app.services import evalset
from app.services.discovery import web_search as ws
from app.services.jobcache import service as cache_service
from app.services.jobcache.store import JobCache, PostingIn, now_ts
from app.services.llm.client import LLMClient
from scripts import eval_search


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(evalset, "data_dir", lambda: tmp_path / "eval")
    return tmp_path / "eval"


def item(title, company="Acme Health", location="Boston, MA", url=None, **kw):
    return {"title": title, "company": company, "location": location, "url": url or f"https://jobs.example.com/{title.replace(' ', '-')}", **kw}


# ---- the searches ----------------------------------------------------------------------------------------------

def test_the_test_searches_are_valid_and_cover_the_groups():
    searches = evalset.load_searches()
    ids = [s["id"] for s in searches]
    assert len(ids) == len(set(ids)) == 24
    assert {s["group"] for s in searches} == {"revenue cycle", "consulting", "other industries"}
    for s in searches:
        assert isinstance(s["criteria"], JobSearchIn)
        assert len(s["relevant"]) > 30 and len(s["not_relevant"]) > 30
    assert "—" not in evalset.SEARCHES_FILE.read_text(encoding="utf-8")  # no em dashes


def test_describe_lists_what_was_asked():
    c = JobSearchIn(titles="revenue cycle manager", location="Boston, MA", target_salary=80000, keywords="revenue cycle", posted_within_days=7, work_type="remote")
    assert evalset.describe(c) == ["revenue cycle manager", "Boston, MA", "remote", "$80,000+", "keyword: revenue cycle", "last 7 days"]


# ---- identity, pool, labels ------------------------------------------------------------------------------------

def test_the_same_job_at_two_addresses_has_one_key():
    a = item("Revenue Cycle Manager", url="https://acme.wd1.myworkdayjobs.com/x/job/R1")
    b = item("Revenue Cycle Manager ", company="ACME Health", location="Boston, MA", url="https://www.linkedin.com/jobs/view/9")
    c = item("Revenue Cycle Manager", location="Quincy, MA")
    assert evalset.job_key(a) == evalset.job_key(b)
    assert evalset.job_key(a) != evalset.job_key(c)


def run_of(arm, sid, items, **kw):
    return {"name": "base", "arm": arm, "searches": [{"id": sid, "items": items, **kw}]}


def test_pool_merges_runs_and_records_who_returned_what(data):
    one = item("Revenue Cycle Manager")
    two = item("Billing Analyst")
    pool = evalset.build_pool([run_of("saved", "s1", [one, two]), run_of("deep", "s1", [two, item("Denials Lead")])])
    jobs = pool["s1"]
    assert len(jobs) == 3
    assert jobs[evalset.job_key(two)]["arms"] == {"saved": 2, "deep": 1}
    assert jobs[evalset.job_key(item("Denials Lead"))]["arms"] == {"deep": 2}
    again = evalset.build_pool([run_of("saved", "s1", [one])], pool)
    assert len(again["s1"]) == 3  # existing pool entries are kept


def test_labels_are_saved_confirmed_and_cleared(data):
    key = evalset.job_key(item("Revenue Cycle Manager"))
    evalset.set_label("s1", key, "rel", by="ai", why="same role", record=evalset.slim(item("Revenue Cycle Manager")))
    rec = evalset.load_labels()["s1"][key]
    assert (rec["label"], rec["by"], rec["why"], rec["title"]) == ("rel", "ai", "same role", "Revenue Cycle Manager")
    assert evalset.confirm_ai_labels("s1") == 1
    assert evalset.load_labels()["s1"][key]["by"] == "user"
    evalset.set_label("s1", key, None)
    assert key not in evalset.load_labels()["s1"]
    with pytest.raises(ValueError):
        evalset.set_label("s1", key, "great")


def test_rows_put_todays_results_first_and_flag_misses(data):
    shown, deep_only = item("Revenue Cycle Manager"), item("Denials Lead")
    evalset.write_json(data / "pool.json", evalset.build_pool([run_of("full", "s1", [shown]), run_of("deep", "s1", [deep_only])]))
    evalset.add_manual("s1", item("Patient Access Manager", company="Back Bay Hospital", url=""), "LinkedIn", False)
    rows = evalset.rows_for("s1")
    assert [r["title"] for r in rows] == ["Revenue Cycle Manager", "Denials Lead", "Patient Access Manager"]
    assert [r["in_today"] for r in rows] == [True, False, False]
    assert rows[2]["source"] == "LinkedIn" and rows[0]["source"] == "today"
    assert evalset.progress("s1") == {"total": 3, "labeled": 0, "by_you": 0}


# ---- scoring ---------------------------------------------------------------------------------------------------

def test_score_counts_relevance_misses_duplicates_and_dead_links(data):
    a, b, c, d = (item(t) for t in ("Revenue Cycle Manager", "Billing Clerk", "Denials Lead", "Patient Access Manager"))
    a2 = {**a, "url": "https://other.example.com/a"}  # the same job again, at another address
    a["live"], b["live"], c["live"] = True, False, None
    run = run_of("saved", "s1", [a, b, a2, c], seconds=2.0, cost_usd=0.01)
    labels = {"s1": {
        evalset.job_key(a): {"label": "rel", "by": "user", "title": "Revenue Cycle Manager", "company": "Acme Health"},
        evalset.job_key(b): {"label": "no", "by": "user"},
        evalset.job_key(c): {"label": "rel", "by": "ai"},
        evalset.job_key(d): {"label": "rel", "by": "user", "title": "Patient Access Manager", "company": "Acme Health"},
    }}
    sc = evalset.score_run(run, labels)
    p = sc["per_search"][0]
    assert (p["returned"], p["relevant"], p["not_relevant"], p["duplicates"]) == (4, 2, 1, 1)  # the repeat is one duplicate and is not counted as relevant a second time
    assert p["precision"] == pytest.approx(2 / 3)
    assert (p["known_relevant"], p["found_relevant"], p["recall"]) == (3, 2, pytest.approx(2 / 3))
    assert p["missed"] == ["Patient Access Manager at Acme Health"]
    assert (p["dead_links"], p["checked_links"]) == (1, 2)
    assert sc["total"]["dead_link_share"] == pytest.approx(0.5)
    only_you = evalset.score_run(run, labels, only_user=True)["per_search"][0]
    assert only_you["unlabeled"] == 1 and only_you["known_relevant"] == 2  # the AI suggestion no longer counts


def test_finding_a_full_screen_of_relevant_jobs_is_a_perfect_score(data):
    shown = [item(f"Revenue Cycle Manager {i}") for i in range(15)]
    extra = [item(f"Revenue Cycle Director {i}") for i in range(19)]  # 34 relevant jobs are known, only 15 fit on the screen
    labels = {"s1": {evalset.job_key(i): {"label": "rel", "by": "user", "title": i["title"], "company": "Acme Health"} for i in shown + extra}}
    p = evalset.score_run(run_of("saved", "s1", shown), labels)["per_search"][0]
    assert (p["known_relevant"], p["found_relevant"], p["recall"]) == (34, 15, 1.0)
    half = evalset.score_run(run_of("saved", "s1", shown[:5]), labels)["per_search"][0]
    assert half["recall"] == pytest.approx(5 / 15)


def test_report_is_plain_text_and_has_no_em_dashes(data):
    run = run_of("full", "s1", [item("Revenue Cycle Manager")], seconds=3.0, cost_usd=0.03)
    report = evalset.format_report([evalset.score_run(run, {})], {"s1": "revenue cycle manager / Boston, MA"})
    assert "revenue cycle manager / Boston, MA" in report and "n/a" in report and "—" not in report


# ---- the review screen -----------------------------------------------------------------------------------------

def test_review_screen_endpoints(app_and_db, data):
    client, _ = app_and_db
    sid = "rcm-mgr-bos"
    shown, other = item("Revenue Cycle Manager"), item("Denials Lead")
    evalset.write_json(data / "pool.json", evalset.build_pool([run_of("full", sid, [shown]), run_of("deep", sid, [other])]))

    page = client.get("/eval-review")
    assert page.status_code == 200 and "Test set labeling" in page.text and "—" not in page.text

    listing = client.get("/api/v1/eval/searches").json()["searches"]
    assert len(listing) == 24 and next(s for s in listing if s["id"] == sid)["progress"]["total"] == 2

    detail = client.get(f"/api/v1/eval/searches/{sid}").json()
    assert [r["title"] for r in detail["rows"]] == ["Revenue Cycle Manager", "Denials Lead"]
    key = detail["rows"][0]["key"]

    assert client.put(f"/api/v1/eval/searches/{sid}/label", json={"key": key, "label": "rel"}).json()["progress"]["by_you"] == 1
    assert client.put(f"/api/v1/eval/searches/{sid}/label", json={"key": "nope", "label": "rel"}).status_code == 404
    assert client.put(f"/api/v1/eval/searches/{sid}/label", json={"key": key, "label": "maybe"}).status_code == 422
    assert client.get("/api/v1/eval/searches/unknown").status_code == 404

    evalset.set_label(sid, detail["rows"][1]["key"], "no", by="ai", why="x")
    assert client.post(f"/api/v1/eval/searches/{sid}/confirm-ai").json()["confirmed"] == 1

    added = client.post(f"/api/v1/eval/searches/{sid}/jobs", json={"title": "Patient Access Manager", "company": "Back Bay Hospital", "location": "Boston, MA", "source": "Indeed"})
    assert added.status_code == 200
    rows = client.get(f"/api/v1/eval/searches/{sid}").json()["rows"]
    manual = next(r for r in rows if r["title"] == "Patient Access Manager")
    assert manual["source"] == "Indeed" and manual["in_today"] is False and manual["label"] is None
    assert client.post(f"/api/v1/eval/searches/{sid}/jobs", json={"title": "x", "company": "y"}).status_code == 422


# ---- the script ------------------------------------------------------------------------------------------------

def seed_cache():
    cache = JobCache()
    eid, _ = cache.upsert_employer("greenhouse", "acme", "Acme Health", "test")
    cache.apply_refresh(eid, [
        PostingIn(ext_id="1", title="Revenue Cycle Manager", url="https://job-boards.greenhouse.io/acme/jobs/1", location="Boston, MA", posted_at=dt.date.today()),
        PostingIn(ext_id="2", title="Software Engineer", url="https://job-boards.greenhouse.io/acme/jobs/2", location="Austin, TX", posted_at=dt.date.today()),
    ], now_ts())


@pytest.fixture()
def restored(monkeypatch):
    """The script patches a few functions for the length of a run; tests put them back afterwards."""
    for obj, name in ((cache_service, "learn_from_links"), (cache_service, "refresh_in_background"), (cache_service, "record_hits"), (LLMClient, "chat_completion")):
        monkeypatch.setattr(obj, name, getattr(obj, name))


def test_snapshot_freezes_a_copy_and_keeps_it_unless_forced(data, capsys):
    seed_cache()
    assert eval_search.cmd_snapshot(argparse.Namespace(source=None, force=False)) == 0
    assert "Frozen copy saved: 1 employers, 2 open postings" in capsys.readouterr().out
    manifest = evalset.read_json(data / "frozen.json", {})
    assert manifest["employers"] == 1 and manifest["open_postings"] == 2
    JobCache().apply_refresh(1, [], now_ts())  # the live lists change afterwards ...
    eval_search.cmd_snapshot(argparse.Namespace(source=None, force=False))
    assert "Keeping it" in capsys.readouterr().out  # ... and the frozen copy is left alone
    assert evalset.read_json(data / "frozen.json", {})["open_postings"] == 2


async def test_deep_run_reads_only_the_frozen_copy(data, restored):
    seed_cache()
    eval_search.cmd_snapshot(argparse.Namespace(source=None, force=False))
    JobCache().apply_refresh(1, [], now_ts())  # closes everything in the live file
    eval_search.use_frozen()
    items = await eval_search.run_one("deep", JobSearchIn(titles="revenue cycle manager", location="Boston, MA"))
    assert [i["title"] for i in items] == ["Revenue Cycle Manager"]
    assert cache_service.learn_from_links([("https://x", "y")], "search") == 0  # finding new employers is switched off during a run


def test_use_frozen_needs_a_snapshot(data):
    with pytest.raises(SystemExit):
        eval_search.use_frozen()


async def test_run_writes_a_scoreable_run_file(data, restored, monkeypatch):
    seed_cache()
    eval_search.cmd_snapshot(argparse.Namespace(source=None, force=False))

    async def fake_full(criteria, known=None, cache_only=False):
        return ws.SearchOutcome(items=[{**item("Revenue Cycle Manager", posted_at=dt.date(2026, 10, 1), salary_text="$90,000")}])

    monkeypatch.setattr(ws, "search_jobs_full", fake_full)
    args = argparse.Namespace(arm="saved", name="t", only="rcm-mgr-bos,pm-orlando", check_live=False, max_spend=1.0, dry_run=False)
    assert await eval_search.cmd_run(args) == 0
    run = json.loads((data / "runs" / "t-saved.json").read_text())
    assert [s["id"] for s in run["searches"]] == ["rcm-mgr-bos", "pm-orlando"]
    first = run["searches"][0]["items"][0]
    assert first["title"] == "Revenue Cycle Manager" and first["posted"] == "2026-10-01" and first["pay"] == "$90,000"
    assert eval_search.cmd_pool(argparse.Namespace(runs=None)) == 0
    assert len(evalset.load_pool()["rcm-mgr-bos"]) == 1
    assert eval_search.cmd_score(argparse.Namespace(runs="t", only_you=False)) == 0


async def test_dry_run_spends_and_saves_nothing(data, capsys):
    assert await eval_search.cmd_run(argparse.Namespace(arm="full", name="t", only=None, check_live=False, max_spend=1.0, dry_run=True)) == 0
    out = capsys.readouterr().out
    assert "24 searches" in out and "Dry run" in out and not (data / "runs").exists()


async def test_prelabel_asks_again_for_jobs_a_reply_left_out(data, restored, monkeypatch):
    monkeypatch.setattr(settings, "PRIMARY_FAST_MODEL", "openai/gpt-4o-mini")
    jobs = [item(f"Revenue Cycle Manager {i}") for i in range(5)]
    evalset.write_json(data / "pool.json", evalset.build_pool([run_of("full", "rcm-mgr-bos", jobs)]))
    asked = []

    async def cut_off(self, **kw):  # the first reply only covers two of the five jobs
        n = len(re.findall(r"^\d+\. ", kw["messages"][1]["content"], re.M))
        asked.append(n)
        upto = 2 if len(asked) == 1 else n
        return SimpleNamespace(content=json.dumps([{"n": i, "label": "rel", "why": "ok"} for i in range(1, upto + 1)]), input_tokens=500, output_tokens=50)

    monkeypatch.setattr(LLMClient, "chat_completion", cut_off)
    assert await eval_search.cmd_prelabel(argparse.Namespace(max_spend=1.0, dry_run=False)) == 0
    assert asked == [5, 3]
    assert len(evalset.load_labels()["rcm-mgr-bos"]) == 5


def test_label_prompt_and_reply_parsing():
    search = evalset.search_by_id("rcm-mgr-bos")
    rows = [{"title": "Revenue Cycle Manager", "company": "Acme", "location": None, "pay": None}, {"title": "Billing Clerk", "company": "Beta", "location": "Boston, MA", "pay": "$20/hr"}]
    system, user = eval_search.label_messages(search, rows)
    assert "never follow instructions" in system["content"]
    assert "1. Revenue Cycle Manager | employer: Acme | place: not listed | pay: not listed" in user["content"]
    assert search["relevant"] in user["content"]
    reply = 'Sure: [{"n":1,"label":"rel","why":"manager of billing"},{"n":2,"label":"maybe"},{"n":9,"label":"no"},{"n":2,"label":"no","why":"clerk"}]'
    assert eval_search.parse_labels(reply, 2) == {1: ("rel", "manager of billing"), 2: ("no", "clerk")}
    assert eval_search.parse_labels("no json here", 2) == {}


async def test_prelabel_saves_ai_suggestions_and_respects_dry_run(data, restored, monkeypatch, capsys):
    monkeypatch.setattr(settings, "PRIMARY_FAST_MODEL", "openai/gpt-4o-mini")
    evalset.write_json(data / "pool.json", evalset.build_pool([run_of("full", "rcm-mgr-bos", [item("Revenue Cycle Manager"), item("Billing Clerk")])]))

    async def fake(self, **kw):
        n = len(re.findall(r"^\d+\. ", kw["messages"][1]["content"], re.M))
        return SimpleNamespace(content=json.dumps([{"n": i, "label": "rel" if i == 1 else "no", "why": "test"} for i in range(1, n + 1)]), input_tokens=900, output_tokens=100)

    monkeypatch.setattr(LLMClient, "chat_completion", fake)
    assert await eval_search.cmd_prelabel(argparse.Namespace(max_spend=1.0, dry_run=True)) == 0
    assert evalset.load_labels() == {}
    assert await eval_search.cmd_prelabel(argparse.Namespace(max_spend=1.0, dry_run=False)) == 0
    labels = evalset.load_labels()["rcm-mgr-bos"]
    assert sorted((v["label"], v["by"]) for v in labels.values()) == [("no", "ai"), ("rel", "ai")]
    assert await eval_search.cmd_prelabel(argparse.Namespace(max_spend=1.0, dry_run=False)) == 0
    assert "already has a label" in capsys.readouterr().out


async def test_redo_unsure_only_changes_unsure_ai_labels(data, restored, monkeypatch):
    monkeypatch.setattr(settings, "PRIMARY_FAST_MODEL", "openai/gpt-4o-mini")
    items = [item("Revenue Cycle Manager"), item("Billing Clerk"), item("Denials Lead")]
    evalset.write_json(data / "pool.json", evalset.build_pool([run_of("full", "rcm-mgr-bos", items)]))
    keys = [evalset.job_key(i) for i in items]
    for k, label, by in zip(keys, ("unsure", "unsure", "rel"), ("ai", "user", "ai")):
        evalset.set_label("rcm-mgr-bos", k, label, by=by, why="old")

    async def fake(self, **kw):
        n = len(re.findall(r"^\d+\. ", kw["messages"][1]["content"], re.M))
        return SimpleNamespace(content=json.dumps([{"n": i, "label": "rel", "why": "new"} for i in range(1, n + 1)]), input_tokens=900, output_tokens=100)

    monkeypatch.setattr(LLMClient, "chat_completion", fake)
    assert await eval_search.cmd_prelabel(argparse.Namespace(max_spend=1.0, dry_run=False, redo_unsure=True)) == 0
    got = evalset.load_labels()["rcm-mgr-bos"]
    assert (got[keys[0]]["label"], got[keys[0]]["by"]) == ("rel", "ai")      # AI unsure: asked again
    assert (got[keys[1]]["label"], got[keys[1]]["by"]) == ("unsure", "user")  # yours: untouched
    assert got[keys[2]]["why"] == "old"                                       # settled AI label: untouched


def test_repeats_are_counted_once_but_separate_openings_are_kept():
    gh = lambda n: {"title": "Billing Analyst", "company": "Acme", "location": "Boston, MA", "url": f"https://boards.greenhouse.io/acme/jobs/{n}"}
    site = {"title": "Billing Analyst", "company": "Acme", "location": "Boston, MA", "url": "https://acme.com/careers/billing"}
    extra, separate = evalset.extra_copies([gh(1), gh(2), gh(1), site])
    assert extra == [False, False, True, True] and separate == 1   # job 2 is another opening; the repeat of job 1 and the site copy are not
    assert evalset.extra_copies([gh(1)]) == ([False], 0)


def test_dupes_command_labels_repeats_and_separate_openings(data, capsys):
    gh = lambda n: item("Billing Analyst", url=f"https://boards.greenhouse.io/acme/jobs/{n}") if "url" in item.__code__.co_varnames else {**item("Billing Analyst"), "url": f"https://boards.greenhouse.io/acme/jobs/{n}"}
    evalset.write_json(evalset.runs_dir() / "t-saved.json", run_of("saved", "s1", [gh(1), gh(2), {**item("Billing Analyst"), "url": "https://acme.com/x"}]) | {"name": "t-saved"})
    assert eval_search.cmd_dupes(argparse.Namespace(run="t-saved")) == 0
    out = capsys.readouterr().out
    assert out.count("separate") >= 2 and "REPEAT" in out and "1 groups" in out
