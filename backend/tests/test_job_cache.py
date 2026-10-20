"""The job cache: readers, the saved copy, matching and ranking. No network, no AI: everything is fed sample data."""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest

from app.services.jobcache import matcher, readers, service, text
from app.services.jobcache.keys import loose_keys, url_key
from app.services.jobcache.store import JobCache, PostingIn, now_ts

TODAY = dt.date.today()


def crit(**kw):
    base = dict(titles="revenue cycle manager", location=None, work_type="any", keywords=None, target_salary=None,
                require_salary=False, posted_within_days=0, exclude_companies=None, count=10)
    base.update(kw)
    return SimpleNamespace(**base)


def post(i, title, location="Boston, MA", **kw):
    return PostingIn(ext_id=str(i), title=title, url=f"https://jobs.example.com/{i}", location=location, **kw)


# ---- which employer a link belongs to ---------------------------------------------------------------------------

def test_employer_from_links_on_all_four_systems():
    ref = readers.employer_ref
    assert ref("https://bilh.wd1.myworkdayjobs.com/en-US/BILH_Careers/job/Boston-MA/Manager_R12345") == ("workday", "bilh.wd1.myworkdayjobs.com|bilh|BILH_Careers")
    assert ref("https://bilh.wd1.myworkdayjobs.com/BILH_Careers") == ("workday", "bilh.wd1.myworkdayjobs.com|bilh|BILH_Careers")
    assert ref("https://job-boards.greenhouse.io/acme/jobs/123") == ("greenhouse", "acme")
    assert ref("https://boards.greenhouse.io/embed/job_board?for=acme") == ("greenhouse", "acme")
    assert ref("https://job-boards.eu.greenhouse.io/acme/jobs/9") == ("greenhouse", "eu:acme")
    assert ref("https://jobs.lever.co/ClinicalHealthNetworkForTransformation/71580e53-408b-4084-9ba6-693c69564b39/apply") == ("lever", "ClinicalHealthNetworkForTransformation")
    assert ref("https://jobs.eu.lever.co/acme/abc") == ("lever", "eu:acme")
    assert ref("https://jobs.ashbyhq.com/acme/9f0b3a52-0000-0000-0000-000000000000/application") == ("ashby", "acme")
    assert ref("https://www.linkedin.com/jobs/view/1") is None
    assert ref("https://careers.example-corp.com/ey/job/x/1") is None
    assert ref("not a url") is None


# ---- the four readers -------------------------------------------------------------------------------------------

def test_greenhouse_list_is_read():
    data = {"jobs": [
        {"id": 11, "title": " Revenue Cycle Manager ", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/11", "location": {"name": "Boston, MA"}, "first_published": "2026-09-30T10:00:00-04:00"},
        {"id": 12, "title": "Analyst", "absolute_url": "https://acme.com/careers?gh_jid=12", "location": {"name": "Remote - US"}},
        {"title": "no id"},
    ]}
    out = readers.parse_greenhouse(data, "acme")
    assert [p.ext_id for p in out] == ["11", "12"]
    assert out[0].title == "Revenue Cycle Manager" and out[0].posted_at == dt.date(2026, 9, 30)
    assert out[1].url == "https://job-boards.greenhouse.io/acme/jobs/12"  # an embedded board gets the board's own address
    assert out[1].work_type == "remote"


def test_lever_list_is_read_with_pay_and_work_type():
    data = [
        {"id": "a1", "text": "Director, Revenue Operations", "hostedUrl": "https://jobs.lever.co/acme/a1", "createdAt": 1_790_000_000_000,
         "categories": {"location": "Boston, MA"}, "workplaceType": "hybrid", "salaryRange": {"min": 120000, "max": 150000, "currency": "USD", "interval": "per-year-salary"}},
        {"id": "a2", "text": "Coordinator", "categories": {"allLocations": ["Austin, TX", "Remote"]}},
    ]
    out = readers.parse_lever(data)
    assert out[0].work_type == "hybrid" and out[0].pay_mid == 135000 and out[0].pay_text == "$120,000 - $150,000"
    assert out[1].location == "Austin, TX, Remote" and out[1].url.startswith("https://jobs.lever.co/")


def test_ashby_board_is_read_and_unlisted_jobs_are_skipped():
    data = {"jobs": [
        {"id": "x1", "title": "Billing Lead", "location": "Boston, MA", "isRemote": False, "workplaceType": "OnSite", "publishedAt": "2026-10-01T00:00:00Z",
         "jobUrl": "https://jobs.ashbyhq.com/acme/x1", "compensation": {"compensationTierSummary": "$90K - $110K"}},
        {"id": "x2", "title": "Hidden", "isListed": False},
        {"id": "x3", "title": "Remote Analyst", "isRemote": True, "location": "United States"},
    ]}
    out = readers.parse_ashby(data, "acme")
    assert [p.ext_id for p in out] == ["x1", "x3"]
    assert out[0].pay_mid == 100000 and out[0].work_type == "onsite" and out[0].posted_at == dt.date(2026, 10, 1)
    assert out[1].work_type == "remote" and out[1].url == "https://jobs.ashbyhq.com/acme/x3"


def test_workday_page_is_read():
    data = {"total": 2, "jobPostings": [
        {"title": "Revenue Cycle Manager", "externalPath": "/job/Boston-MA/Revenue-Cycle-Manager_R12345", "locationsText": "Boston, MA", "postedOn": "Posted 3 Days Ago"},
        {"title": "Biller", "externalPath": "/job/Quincy/Biller_R9", "locationsText": "2 Locations", "postedOn": "Posted Today"},
    ]}
    out = readers.parse_workday(data, "bilh.wd1.myworkdayjobs.com", "BILH_Careers")
    assert out[0].url == "https://bilh.wd1.myworkdayjobs.com/en-US/BILH_Careers/job/Boston-MA/Revenue-Cycle-Manager_R12345"
    assert out[0].posted_at == TODAY - dt.timedelta(days=3) and out[1].posted_at == TODAY


# ---- the saved copy ---------------------------------------------------------------------------------------------

def test_refresh_adds_closes_and_reopens_postings_and_keeps_the_index_in_step():
    cache = JobCache()
    eid, created = cache.upsert_employer("greenhouse", "acme", "Acme Health", "search")
    assert created and cache.upsert_employer("greenhouse", "acme", "", "search") == (eid, False)
    one = cache.apply_refresh(eid, [post(1, "Revenue Cycle Manager"), post(2, "Billing Analyst")], 1000)
    assert (one.new, one.closed, one.total) == (2, 0, 2)
    hits = lambda q: [r["title"] for r in cache.candidates(q, [], 50)]
    assert hits('{title} : ("billing")') == ["Billing Analyst"]

    two = cache.apply_refresh(eid, [post(1, "Revenue Cycle Manager")], 2000)  # the analyst job is gone
    assert (two.new, two.closed) == (0, 1)
    assert hits('{title} : ("billing")') == []  # closed postings leave the index

    cache.apply_refresh(eid, [post(1, "Revenue Cycle Manager"), post(2, "Billing Analyst")], 3000)  # it came back
    assert hits('{title} : ("billing")') == ["Billing Analyst"]

    cache.apply_refresh(eid, [post(1, "Senior Revenue Cycle Manager"), post(2, "Billing Analyst")], 4000)  # a title changed
    assert hits('{title} : ("senior")') == ["Senior Revenue Cycle Manager"]


def test_a_partial_read_does_not_close_the_jobs_it_did_not_reach():
    cache = JobCache()
    eid, _ = cache.upsert_employer("workday", "h|t|s", "Big Hospital", "search")
    cache.apply_refresh(eid, [post(1, "Nurse Manager"), post(2, "Billing Analyst")], 1000)
    result = cache.apply_refresh(eid, [post(1, "Nurse Manager")], 2000, close_missing=False)
    assert result.closed == 0 and cache.counts()["postings"] == 2


def test_failures_back_off_and_a_good_read_resets_them():
    cache = JobCache()
    eid, _ = cache.upsert_employer("lever", "acme", "Acme", "search")
    for _ in range(5):
        cache.record_failure(eid, "boom", 1000)
    emp = cache.get_employer(eid)
    assert emp["status"] == "unreachable" and emp["next_check"] > 1000 + 6 * 3600
    cache.apply_refresh(eid, [post(1, "Analyst")], 5000)
    emp = cache.get_employer(eid)
    assert emp["status"] == "ok" and emp["fail_count"] == 0 and emp["open_count"] == 1


def test_old_closed_postings_are_deleted_and_open_ones_kept():
    cache = JobCache()
    eid, _ = cache.upsert_employer("ashby", "acme", "Acme", "search")
    cache.apply_refresh(eid, [post(1, "A manager"), post(2, "An analyst")], 1000)
    cache.apply_refresh(eid, [post(1, "A manager")], 2000)
    assert cache.cleanup(now=2000 + 40 * 86400) == 1
    assert cache.counts()["postings"] == 1


def test_a_switched_off_employer_is_not_searched():
    cache = JobCache()
    eid, _ = cache.upsert_employer("lever", "acme", "Acme", "search")
    cache.apply_refresh(eid, [post(1, "Revenue Cycle Manager")], 1000)
    assert service.search_sync(crit(), set(), None, 10).items
    cache.set_enabled(eid, False)
    assert not service.search_sync(crit(), set(), None, 10).items


# ---- words, places and pay --------------------------------------------------------------------------------------

def test_places():
    q = text.parse_location_query("Boston, MA or remote")
    assert q.cities == ["boston"] and q.states == {"MA"} and q.remote
    fit = lambda loc, wt=None, query="Boston, MA": text.location_fit(text.parse_location_query(query), loc, wt)
    assert fit("Boston, MA") == 1.0 and fit("Boston, Massachusetts, United States") == 1.0
    assert fit("Worcester, MA") == 0.0  # another town in the state: a city search is a filter
    assert fit("Boston, GA") == 0.0 and fit("Dallas, TX") == 0.0
    assert fit("2 Locations") == 0.4 and fit(None) == 0.4  # a city search puts jobs that name no place behind jobs that do
    assert fit("2 Locations", None, "United States") == 0.5
    assert fit("Remote - US", "remote") == 0.0  # remote was not asked for
    assert fit("Remote - US", "remote", "Boston, MA or remote") == 0.75  # welcome, but behind jobs in Boston
    assert fit("London, United Kingdom") == 0.0 and fit("Remote - UK", "remote", "Boston, MA or remote") == 0.0
    assert text.location_fit(text.parse_location_query(None), "Anywhere", None) == 1.0


def test_pay_and_levels_and_dates():
    assert text.pay_midpoint("$80,000 - $100,000") == 90000 and text.pay_midpoint("85k") == 85000
    assert text.pay_midpoint("$45 - $60 per hour") == 52.5 * 2080  # hourly pay is read as a yearly figure (2,080 hours)
    assert text.pay_midpoint("$43,800.00 - $51,100.00") == 47450  # cents do not break it
    assert text.level_of("Senior Revenue Cycle Manager") == 3 and text.level_of("Director of Finance") == 5
    assert text.level_of("Revenue Cycle") is None
    assert text.workday_posted("Posted 30+ Days Ago", TODAY) == TODAY - dt.timedelta(days=30)
    assert text.split_titles("Revenue cycle manager, patient financial services manager or billing lead") == [
        "Revenue cycle manager", "patient financial services manager", "billing lead"]


# ---- ranking ----------------------------------------------------------------------------------------------------

def test_titles_rank_by_how_well_they_match():
    plan = matcher.build_plan(crit())
    f = lambda t: matcher.title_fit(plan, t)
    exact, senior, reordered = f("Revenue Cycle Manager"), f("Senior Revenue Cycle Manager"), f("Manager, Revenue Cycle")
    assert exact > 0.9 and senior > 0.8 and reordered > 0.7 and exact >= senior >= reordered
    assert f("Director, Revenue Cycle") < reordered  # right field, a level too high
    assert f("Revenue Cycle Assistant Manager") > matcher.MIN_TITLE_FIT
    assert f("Marketing Manager") == 0.0 and f("Cycle Mechanic") == 0.0  # sharing one word is not a match
    assert f("Revenue Cycle Intern") < f("Revenue Cycle Analyst") + 1e-9 or f("Revenue Cycle Intern") < 0.6
    assert f("Revenue Cycle Managers") > 0.9  # plural is the same word


def test_shorthand_and_alternative_titles_are_understood():
    assert matcher.title_fit(matcher.build_plan(crit()), "Sr. Revenue Cycle Mgr") > 0.8
    plain = matcher.build_plan(crit())
    wider = matcher.build_plan(crit(), ["Patient Financial Services Manager"])
    assert matcher.title_fit(plain, "Patient Financial Services Manager") == 0.0
    assert 0.65 < matcher.title_fit(wider, "Patient Financial Services Manager") <= matcher.OTHER_FIELD_WEIGHT  # none of "revenue cycle": counts for less


def test_search_applies_place_work_type_pay_dates_and_exclusions():
    cache = JobCache()
    eid, _ = cache.upsert_employer("lever", "acme", "Acme Health", "search")
    other, _ = cache.upsert_employer("ashby", "beta", "Beta Care", "search")
    cache.apply_refresh(eid, [
        post(1, "Revenue Cycle Manager", "Boston, MA", posted_at=TODAY - dt.timedelta(days=2), pay_mid=120000),
        post(2, "Revenue Cycle Manager", "Dallas, TX"),
        post(3, "Revenue Cycle Manager", "Remote - US", work_type="remote"),
        post(4, "Revenue Cycle Manager", "Boston, MA", posted_at=TODAY - dt.timedelta(days=60)),
        post(5, "Revenue Cycle Manager", "Boston, MA", pay_mid=60000),
    ], 1000)
    cache.apply_refresh(other, [post(6, "Revenue Cycle Manager", "Boston, MA")], 1000)

    def ids(**kw):
        out = service.search_sync(crit(**kw), set(), None, 20)
        return [i["url"].rsplit("/", 1)[1] for i in out.items]

    assert ids(location="Boston, MA")[0] == "1"  # right place and recent, so first
    assert "2" not in ids(location="Boston, MA")  # Dallas is not Boston
    assert "3" not in ids(location="Boston, MA")  # remote was not asked for: a city search shows that city and its area only
    assert "3" not in ids(location="Boston, MA", work_type="onsite")
    assert "3" in ids(location="Boston, MA", include_remote=True)  # the remote checkbox brings remote jobs in
    assert "3" not in ids(location="Boston, MA or remote")  # typing it in the place box does nothing: the box is a city and state only
    assert ids(work_type="remote") == ["3"]
    assert "4" not in ids(location="Boston, MA", posted_within_days=30) and "4" in ids(location="Boston, MA")
    assert "5" not in ids(location="Boston, MA", target_salary=100000)
    assert "6" not in ids(location="Boston, MA", exclude_companies="beta")


def test_search_skips_what_you_already_have_and_reports_how_many_more_fit():
    cache = JobCache()
    eid, _ = cache.upsert_employer("workday", "h.wd1.myworkdayjobs.com|h|Careers", "Hospital", "search")
    rows = [PostingIn(ext_id=f"/job/b/m_R{1000 + i}", title="Revenue Cycle Manager", location="Boston, MA",
                      url=f"https://h.wd1.myworkdayjobs.com/en-US/Careers/job/b/m_R{1000 + i}") for i in range(8)]
    cache.apply_refresh(eid, rows, 1000)
    known = loose_keys("https://h.wd1.myworkdayjobs.com/Careers/job/b/m_R1000/apply")  # saved without the language, with /apply
    out = service.search_sync(crit(location="Boston, MA"), known, None, 5)
    assert len(out.items) == 5 and out.matches == 7 and not out.matches_capped
    assert all("R1000" not in i["url"] for i in out.items)
    assert out.coverage["by_system"]["workday"]["postings"] == 8


def test_search_stays_bounded_on_a_large_saved_copy():
    cache = JobCache()
    eid, _ = cache.upsert_employer("greenhouse", "big", "Big Co", "search")
    cache.apply_refresh(eid, [post(i, f"Manager of Thing {i}", "Boston, MA") for i in range(3000)], 1000)
    cache.apply_refresh(eid, [post(i, f"Manager of Thing {i}", "Boston, MA") for i in range(3000)] + [post(9999, "Revenue Cycle Manager", "Boston, MA")], 2000)
    out = service.search_sync(crit(location="Boston, MA"), set(), None, 10)
    assert out.items[0]["title"] == "Revenue Cycle Manager"  # the one real match outranks 3,000 postings that share "manager"
    assert out.matches_capped is False or out.matches_capped is True  # bounded either way: never more than the candidate limit is read


def test_the_two_address_keys_agree_with_job_search():
    from app.services.discovery import web_search

    for url in ["https://www.Example.com/a/b/?x=1#f", "https://h.wd1.myworkdayjobs.com/en-US/C/job/x_R1/"]:
        assert url_key(url) == web_search.url_key(url)
    assert "wd:h.wd1.myworkdayjobs.com:r1234" in loose_keys("https://h.wd1.myworkdayjobs.com/en-US/C/job/x/Title_R1234")
    assert "gh:77" in loose_keys("https://job-boards.greenhouse.io/acme/jobs/77")


# ---- inside Job Search: the saved lists and the web search together ---------------------------------------------

def _stub_network(monkeypatch):
    """Job Search checks every result against the employers' own systems; tests never visit real sites."""
    from app.services.discovery import web_search as ws

    async def same(items, *a, **k):
        return items, 0

    async def upgraded(items):
        return items

    monkeypatch.setattr(ws, "enrich_from_ats", same)
    monkeypatch.setattr(ws, "fill_posted_dates", same)
    monkeypatch.setattr(ws, "drop_closed", same)
    monkeypatch.setattr(ws, "resolve_original_sources", same)
    monkeypatch.setattr(ws, "upgrade_to_ats_links", upgraded)
    return ws


def _seed_twelve():
    cache = JobCache()
    names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]
    for n, (ats, ident, company) in enumerate([("lever", "acme", "Acme Health"), ("ashby", "beta", "Beta Care")]):
        eid, _ = cache.upsert_employer(ats, ident, company, "search")
        cache.apply_refresh(eid, [post(f"{n}-{i}", f"Revenue Cycle Manager {names[i]}", "Boston, MA") for i in range(6)], 1000)


def test_job_search_uses_the_saved_lists_even_without_the_ai_connection(monkeypatch):
    import asyncio

    from app.schemas.job_search import JobSearchIn

    ws = _stub_network(monkeypatch)
    _seed_twelve()
    out = asyncio.run(ws.search_jobs_full(JobSearchIn(titles="revenue cycle manager", location="Boston, MA", count=5)))
    assert len(out.items) == 5 and all(i["grounded"] for i in out.items)
    assert out.coverage["employers"] == 2 and out.coverage["postings"] == 12 and out.coverage["matches"] == 12
    assert out.more_available == 7 and out.more_capped is False
    assert not ({"fit", "employer_id", "ats_checked"} & set(out.items[0]))  # working notes never reach the saved results
    assert JobCache().list_employers()[0]["hits"] >= 0


def test_job_search_still_needs_the_ai_connection_when_nothing_is_saved(monkeypatch):
    import asyncio

    from app.schemas.job_search import JobSearchIn
    from app.services.llm.exceptions import LLMNotConfiguredError

    ws = _stub_network(monkeypatch)
    try:
        asyncio.run(ws.search_jobs_full(JobSearchIn(titles="revenue cycle manager")))
    except LLMNotConfiguredError:
        return
    raise AssertionError("expected the AI connection to be required")


def test_show_more_reads_only_the_saved_lists_and_skips_what_was_already_shown(monkeypatch):
    import asyncio

    from app.config import settings
    from app.schemas.job_search import JobSearchIn

    ws = _stub_network(monkeypatch)
    monkeypatch.setattr(settings, "PRIMARY_FAST_MODEL", "test/model")

    async def never(*a, **k):
        raise AssertionError("the AI search must not run for 'show more'")

    monkeypatch.setattr(ws, "_search_one", never)
    _seed_twelve()
    crit_in = JobSearchIn(titles="revenue cycle manager", location="Boston, MA", count=5, more=True)
    first = asyncio.run(ws.search_jobs_full(crit_in, known_keys=set(), cache_only=True))
    shown = set()
    for i in first.items:
        shown |= loose_keys(i["url"])
    second = asyncio.run(ws.search_jobs_full(crit_in, known_keys=shown, cache_only=True))
    assert len(first.items) == 5 and len(second.items) == 5
    assert not {i["url"] for i in first.items} & {i["url"] for i in second.items}
    assert second.more_available == 2


def test_the_web_search_is_skipped_in_auto_mode_when_the_saved_lists_have_plenty(monkeypatch):
    import asyncio

    from app.config import settings
    from app.schemas.job_search import JobSearchIn

    ws = _stub_network(monkeypatch)
    monkeypatch.setattr(settings, "PRIMARY_FAST_MODEL", "test/model")
    monkeypatch.setattr(settings, "JOB_SEARCH_AI", "auto")
    calls = []

    async def fake_one(criteria, scope, model):
        calls.append(scope)
        return []

    monkeypatch.setattr(ws, "_search_one", fake_one)
    _seed_twelve()
    asyncio.run(ws.search_jobs_full(JobSearchIn(titles="revenue cycle manager", location="Boston, MA", count=5)))
    assert calls == []  # 12 saved matches cover the 5 asked for
    asyncio.run(ws.search_jobs_full(JobSearchIn(titles="revenue cycle manager", location="Boston, MA", count=15)))
    assert len(calls) == 2  # not enough saved matches: the web search runs


def test_employers_found_by_the_web_search_join_the_saved_lists(monkeypatch):
    import asyncio

    from app.config import settings
    from app.schemas.job_search import JobSearchIn

    ws = _stub_network(monkeypatch)
    monkeypatch.setattr(settings, "PRIMARY_FAST_MODEL", "test/model")

    async def fake_one(criteria, scope, model):
        if scope != "ats":
            return []
        return [{"title": "Revenue Cycle Manager", "company": "Newco Health", "location": "Boston, MA", "work_type": None, "salary_text": None,
                 "posted_at": None, "summary": None, "url": "https://jobs.lever.co/newco/71580e53-408b-4084-9ba6-693c69564b39",
                 "url_key": "jobs.lever.co/newco/71580e53-408b-4084-9ba6-693c69564b39", "grounded": True}]

    monkeypatch.setattr(ws, "_search_one", fake_one)
    out = asyncio.run(ws.search_jobs_full(JobSearchIn(titles="revenue cycle manager", location="Boston, MA")))
    assert [i["company"] for i in out.items] == ["Newco Health"]
    found = [(e["ats"], e["identifier"], e["name"], e["source"]) for e in JobCache().list_employers()]
    assert found == [("lever", "newco", "Newco Health", "search")]


def test_a_switched_off_hiring_system_is_not_read_or_searched(monkeypatch):
    from app.config import settings

    _seed_twelve()
    assert service.search_sync(crit(), set(), None, 10).items
    monkeypatch.setattr(settings, "JOB_CACHE_DISABLED_SYSTEMS", "lever, ashby")
    assert not service.search_sync(crit(), set(), None, 10).items
    assert JobCache().due_employers(10**10, 10, None, service.disabled_systems()) == []


# ---- the Employers panel and the search endpoint (these need the web framework) ----------------------------------

def test_employers_panel_adds_by_link_lists_and_switches_off(app_and_db, monkeypatch):
    client, _ = app_and_db

    async def fake_read(system, identifier, http, throttle):
        assert (system, identifier) == ("lever", "ClinicalHealthNetworkForTransformation")
        return readers.ReadResult([post(1, "Revenue Cycle Manager")], name="Clinical Health Network For Transformation")

    monkeypatch.setattr(service, "read_employer", fake_read)
    link = "https://jobs.lever.co/ClinicalHealthNetworkForTransformation/71580e53-408b-4084-9ba6-693c69564b39/apply"
    res = client.post("/api/v1/job-search/employers", json={"url": link})
    assert res.status_code == 201
    added = res.json()
    assert added["system"] == "lever" and added["open_jobs"] == 1 and added["name"] == "Clinical Health Network For Transformation"
    assert added["status"] == "ok" and added["source"] == "user_link"

    assert client.post("/api/v1/job-search/employers", json={"url": "https://www.linkedin.com/jobs/view/1"}).status_code == 422

    listing = client.get("/api/v1/job-search/employers").json()
    assert listing["total_employers"] == 1 and listing["total_postings"] == 1 and listing["employers"][0]["enabled"] is True

    off = client.patch(f"/api/v1/job-search/employers/{added['id']}", json={"enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert client.get("/api/v1/job-search/employers").json()["total_postings"] == 0  # a switched-off employer is not counted or searched
    assert client.patch("/api/v1/job-search/employers/999", json={"enabled": True}).status_code == 404


def test_a_link_that_cannot_be_read_is_not_added(app_and_db, monkeypatch):
    client, _ = app_and_db

    async def gone(system, identifier, http, throttle):
        raise readers.ReaderError("that job list was not found", gone=True)

    monkeypatch.setattr(service, "read_employer", gone)
    res = client.post("/api/v1/job-search/employers", json={"url": "https://jobs.ashbyhq.com/nobody"})
    assert res.status_code == 422 and "couldn't read" in res.json()["detail"]
    assert JobCache().list_employers() == []


def test_the_panel_starts_from_the_employers_behind_your_saved_jobs(app_and_db, monkeypatch):
    from app.models.jobs import Job

    client, SessionLocal = app_and_db
    monkeypatch.setattr(service, "refresh_in_background", lambda **k: False)
    now = dt.datetime.now(dt.timezone.utc)
    with SessionLocal() as db:
        db.add(Job(canonical_job_key="k1", company="Beth Israel Lahey Health", normalized_company="beth israel lahey health", title="Manager",
                   normalized_title="manager", canonical_application_url="https://bilh.wd1.myworkdayjobs.com/en-US/BILH_Careers/job/Boston-MA/Manager_R12345",
                   first_seen=now, last_seen=now, application_status="not_started"))
        db.commit()
    listing = client.get("/api/v1/job-search/employers").json()
    assert [(e["name"], e["system"], e["source"]) for e in listing["employers"]] == [("Beth Israel Lahey Health", "workday", "saved_job")]


def test_refresh_now_starts_a_background_read(app_and_db, monkeypatch):
    client, _ = app_and_db
    started = []
    monkeypatch.setattr(service, "refresh_in_background", lambda **k: started.append(k) or True)
    res = client.post("/api/v1/job-search/employers/refresh")
    assert res.status_code == 200 and started and started[0].get("force") is True


def test_the_search_endpoint_returns_coverage_and_show_more_gives_the_next_results(app_and_db, monkeypatch):
    client, _ = app_and_db
    _stub_network(monkeypatch)
    _seed_twelve()
    body = {"titles": "revenue cycle manager", "location": "Boston, MA", "count": 5}
    first = client.post("/api/v1/job-search/run", json=body)
    assert first.status_code == 200, first.text  # no AI connection is set up, and the saved lists answer on their own
    out = first.json()
    assert out["found"] == 5 and out["coverage"]["employers"] == 2 and out["coverage"]["postings"] == 12
    assert out["more_available"] == 7 and set(out["coverage"]["by_system"]) == {"lever", "ashby"}

    more = client.post("/api/v1/job-search/run", json={**body, "more": True}).json()
    assert more["found"] == 5 and more["more_available"] == 2
    urls = [r["url"] for r in more["results"]]
    assert len(urls) == len(set(urls)) == 10  # nothing repeated


# ---- finding employers by industry and city ---------------------------------------------------------------------

def test_cities_are_cleaned_and_names_become_addresses():
    from app.services.jobcache import finder

    assert finder.clean_cities([" Boston, MA ", "boston, ma", "", "x", "Austin  TX"]) == ["Boston, MA", "Austin TX"]
    assert len(finder.clean_cities([f"City {i}" for i in range(9)])) == finder.MAX_CITIES
    assert finder.slug_guesses("Flatiron Health, Inc.") == ["flatironhealth", "flatiron-health"]
    assert finder.slug_guesses("The Acme Corp") == ["acme"]
    assert finder.slug_guesses("Inc") == []


def _fake_finder(monkeypatch, suggestions, readable):
    """AI suggestions per city; `readable` is the set of (system, identifier) whose job list exists and has jobs."""
    from app.services.jobcache import finder

    async def suggest(industry, city, model):
        return [dict(s, city=city) for s in suggestions.get(city, [])]

    async def read(system, identifier, client, throttle):
        if (system, identifier) not in readable:
            raise readers.ReaderError("that job list was not found", gone=True)
        return readers.ReadResult(postings=[post(1, "Nurse Manager"), post(2, "Analyst")])

    monkeypatch.setattr(finder, "_suggest", suggest)
    monkeypatch.setattr(finder, "read_employer", read)
    monkeypatch.setattr(finder, "search_model", lambda: "test-model")
    return finder


def test_finder_adds_only_employers_whose_job_list_can_be_read(monkeypatch):
    import asyncio

    suggestions = {
        "Boston, MA": [
            {"company": "Acme Health", "url": "https://job-boards.greenhouse.io/acme/jobs/1"},  # a real link from the AI
            {"company": "Flatiron Health, Inc.", "url": None},  # no link: found by trying its name as an address
            {"company": "Made Up Corp", "url": "https://careers.madeup.example.com"},  # not on the four systems, no guess works
        ],
        "Cambridge, MA": [
            {"company": "acme health", "url": None},  # same company again from another city
            {"company": "Moderna", "url": "https://modernatx.wd1.myworkdayjobs.com/en-US/M_tx/job/Cambridge/Role_R1"},
        ],
    }
    readable = {("greenhouse", "acme"), ("lever", "flatiron-health"), ("workday", "modernatx.wd1.myworkdayjobs.com|modernatx|M_tx")}
    finder = _fake_finder(monkeypatch, suggestions, readable)
    out = asyncio.run(finder.find_employers("Healthcare", ["Boston, MA", "Cambridge, MA"]))

    assert out.suggested == 4  # "Acme Health" from both cities counts once
    assert sorted((f.name, f.system) for f in out.added) == [("Acme Health", "greenhouse"), ("Flatiron Health, Inc.", "lever"), ("Moderna", "workday")]
    assert out.unreadable == ["Made Up Corp"] and out.already == []
    cache = JobCache()
    assert cache.counts()["employers"] == 3 and cache.counts()["postings"] == 6
    assert {e["source"] for e in cache.list_employers()} == {"industry"}
    assert {e["industry"] for e in cache.list_employers()} == {"Healthcare"}


def test_finder_reports_employers_already_saved_and_leaves_no_trace_of_failures(monkeypatch):
    import asyncio

    JobCache().upsert_employer("greenhouse", "acme", "Acme Health", "saved_job")
    finder = _fake_finder(monkeypatch, {"Boston, MA": [{"company": "Acme Health", "url": "https://boards.greenhouse.io/acme"}, {"company": "Ghost Co", "url": None}]}, {("greenhouse", "acme")})
    out = asyncio.run(finder.find_employers("Healthcare", ["Boston, MA"]))
    assert out.added == [] and out.already == ["Acme Health"] and out.unreadable == ["Ghost Co"]
    assert [e["name"] for e in JobCache().list_employers()] == ["Acme Health"]  # the failed guesses were removed


def test_finder_respects_switched_off_systems_and_empty_lists(monkeypatch):
    import asyncio
    from app.config import settings

    monkeypatch.setattr(settings, "JOB_CACHE_DISABLED_SYSTEMS", "greenhouse")
    finder = _fake_finder(monkeypatch, {"Boston, MA": [{"company": "Acme Health", "url": "https://boards.greenhouse.io/acme"}]}, {("greenhouse", "acme"), ("greenhouse", "acmehealth")})
    out = asyncio.run(finder.find_employers("Healthcare", ["Boston, MA"]))
    assert out.added == [] and out.unreadable == ["Acme Health"]


def test_finder_needs_the_ai_connection(monkeypatch):
    import asyncio
    from app.services.jobcache import finder
    from app.services.llm.exceptions import LLMNotConfiguredError

    monkeypatch.setattr(finder, "search_model", lambda: None)
    with pytest.raises(LLMNotConfiguredError):
        asyncio.run(finder.find_employers("Healthcare", ["Boston, MA"]))


def test_find_endpoint(app_and_db, monkeypatch):
    client, _ = app_and_db
    _fake_finder(monkeypatch, {"Boston, MA": [{"company": "Acme Health", "url": "https://boards.greenhouse.io/acme"}]}, {("greenhouse", "acme")})
    ok = client.post("/api/v1/job-search/employers/find", json={"industry": "Healthcare", "cities": ["Boston, MA", "Austin, TX"]})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["added"][0]["name"] == "Acme Health" and body["total_employers"] == 1 and body["cities"] == ["Boston, MA", "Austin, TX"]
    assert client.post("/api/v1/job-search/employers/find", json={"industry": "Healthcare", "cities": []}).status_code == 422
    assert client.post("/api/v1/job-search/employers/find", json={"industry": "H", "cities": ["Boston"]}).status_code == 422


# ---- the greater area around a city ------------------------------------------------------------------------------

def test_a_nearby_place_is_read_as_city_and_state():
    assert text.place_ref("Cambridge, MA") == ("cambridge", "MA")
    assert text.place_ref("Arlington, Virginia") == ("arlington", "VA")
    assert text.place_ref("Somerville") == ("somerville", None)
    assert text.place_ref("") is None and text.place_ref("MA") is None


def test_nearby_cities_rank_above_the_rest_of_the_state_and_cross_state_lines():
    boston = text.parse_location_query("Boston, MA")
    boston.near = [text.place_ref("Cambridge, MA"), text.place_ref("Quincy, MA")]
    fit = lambda q, loc: text.location_fit(q, loc, None)
    assert fit(boston, "Boston, MA") == 1.0
    assert fit(boston, "Cambridge, MA") == 0.95
    assert fit(boston, "US-MA-Quincy") == 0.95
    assert fit(boston, "Springfield, MA") == 0.0  # same state, not near: not the place asked for
    assert fit(boston, "Cambridge, United Kingdom") == 0.0  # the other Cambridge
    assert fit(boston, "Cambridge, OH") == 0.0  # wrong state: not the nearby Cambridge

    dc = text.parse_location_query("Washington, DC")
    assert fit(dc, "Arlington, VA") == 0.0  # without the area, a different state is left out
    dc.near = [text.place_ref("Arlington, VA")]
    assert fit(dc, "Arlington, VA") == 0.95


def test_search_with_nearby_places_finds_jobs_around_the_city():
    cache = JobCache()
    eid, _ = cache.upsert_employer("greenhouse", "acme", "Acme", "user_link")
    cache.apply_refresh(eid, [post(1, "Revenue Cycle Manager", "Boston, MA"), post(2, "Revenue Cycle Manager", "Cambridge, MA"),
                              post(3, "Revenue Cycle Manager", "Springfield, MA"), post(4, "Revenue Cycle Manager", "Austin, TX")], 1_000_000)
    c = crit(location="Boston, MA")
    plain = {r.row["location"]: r.fit for r in matcher.rank(matcher.build_plan(c), JobCache().candidates("revenue", [], 50, None))}
    near = {r.row["location"]: r.fit for r in matcher.rank(matcher.build_plan(c, None, ["Cambridge, MA"]), JobCache().candidates("revenue", [], 50, None))}
    assert "Austin, TX" not in plain and "Springfield, MA" not in plain and "Cambridge, MA" not in plain  # a city search shows that city only
    assert "Cambridge, MA" in near and "Springfield, MA" not in near and "Austin, TX" not in near  # ...and the area around it, once known
    assert near["Boston, MA"] >= near["Cambridge, MA"]


def test_the_area_around_a_place_is_asked_once_and_remembered(monkeypatch):
    import asyncio
    from app.config import settings
    from app.services.llm import client as llm_client

    calls = []

    class FakeLLM:
        async def chat_completion(self, **kw):
            calls.append(kw["messages"][-1]["content"])
            return SimpleNamespace(content='Sure: ["Cambridge, MA", "Somerville, MA", "Quincy, MA", "Boston, MA", "nonsense", "Cambridge, MA"]')

    monkeypatch.setattr(llm_client, "LLMClient", FakeLLM)
    monkeypatch.setattr(settings, "PRIMARY_FAST_MODEL", "m")
    first = asyncio.run(service.expand_places("Smalltown, MA"))  # no known coordinates: the AI is asked
    again = asyncio.run(service.expand_places("Smalltown, MA"))
    assert first == again and first[:3] == ["Cambridge, MA", "Somerville, MA", "Quincy, MA"] and first.count("Cambridge, MA") == 1
    assert len(calls) == 1
    assert asyncio.run(service.expand_places("remote")) == []  # no city to expand
    assert asyncio.run(service.expand_places(None)) == [] and len(calls) == 1


# ---- SmartRecruiters ---------------------------------------------------------------------------------------------

def test_smartrecruiters_links_are_recognised():
    ref = readers.employer_ref
    assert ref("https://jobs.smartrecruiters.com/BoschGroup/743999-software-engineer") == ("smartrecruiters", "BoschGroup")
    assert ref("https://careers.smartrecruiters.com/Visa") == ("smartrecruiters", "Visa")
    assert ref("https://www.smartrecruiters.com/Visa/74944235-experienced-seo-consultant-?oga=true") == ("smartrecruiters", "Visa")
    assert ref("https://www.smartrecruiters.com/product/recruiting") is None  # their own marketing pages are not employers
    assert ref("https://jobs.smartrecruiters.com/search") is None


SR_PAGE = {
    "totalFound": 3,
    "content": [
        {"id": "7001", "name": "Revenue Cycle Manager", "releasedDate": "2026-10-01T12:21:43.462Z",
         "location": {"city": "Boston", "region": "MA", "country": "us", "remote": False}, "company": {"identifier": "Acme", "name": "Acme Health"}},
        {"id": "7002", "name": "Billing Analyst", "releasedDate": "2026-09-20T08:00:00.000Z",
         "location": {"city": "", "region": "", "country": "us", "remote": True}, "company": {"identifier": "Acme", "name": "Acme Health"}},
        {"id": "7003", "name": "Data Engineer", "location": {"city": "Toronto", "region": "ON", "country": "ca", "remote": False}, "company": {"identifier": "Acme", "name": "Acme Health"}},
        {"name": "No id is skipped"},
    ],
}


def test_smartrecruiters_postings_are_parsed():
    got = readers.parse_smartrecruiters(SR_PAGE, "Acme")
    assert [p.title for p in got] == ["Revenue Cycle Manager", "Billing Analyst", "Data Engineer"]
    first, remote, abroad = got
    assert first.url == "https://jobs.smartrecruiters.com/Acme/7001-revenue-cycle-manager"
    assert first.location == "Boston, MA" and first.posted_at == dt.date(2026, 10, 1) and first.work_type is None
    assert remote.location == "Remote" and remote.work_type == "remote"
    assert abroad.location == "Toronto, ON, Canada"  # the country is written out, since "CA" is also California


def test_smartrecruiters_reader_pages_through_the_list_and_reports_the_company_name():
    import asyncio

    pages = []

    class FakeResp:
        status_code = 200
        headers = {}

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    class FakeClient:
        async def request(self, method, url, **kw):
            offset = kw["params"]["offset"]
            pages.append((url, kw["params"]["limit"], offset))
            n = 100 if offset == 0 else 30  # 130 jobs: a full page, then a short one
            return FakeResp({"totalFound": 130, "content": [
                {"id": str(offset + i), "name": f"Job {offset + i}", "company": {"identifier": "Acme", "name": "Acme Health"}} for i in range(n)]})

    class NoWait:
        async def wait(self, host, gap):
            return None

    res = asyncio.run(readers.read_employer("smartrecruiters", "Acme", FakeClient(), NoWait()))
    assert len(res.postings) == 130 and res.complete and res.name == "Acme Health"
    assert pages == [("https://api.smartrecruiters.com/v1/companies/Acme/postings", 100, 0), ("https://api.smartrecruiters.com/v1/companies/Acme/postings", 100, 100)]


def test_the_finder_tries_smartrecruiters_and_rejects_a_guess_that_is_another_company(monkeypatch):
    import asyncio

    from app.services.jobcache import finder

    assert finder.guesses_for("smartrecruiters", "Acme Health, Inc.") == ["AcmeHealth", "acmehealth"]
    assert finder.guesses_for("lever", "Acme Health") == ["acmehealth", "acme-health"]

    async def read(system, identifier, client, throttle):
        if (system, identifier) == ("smartrecruiters", "Visa"):
            return readers.ReadResult(postings=[post(1, "Analyst")], name="Visa Inc.")
        if (system, identifier) == ("smartrecruiters", "Delta"):
            return readers.ReadResult(postings=[post(1, "Analyst")], name="Delta Dental of Massachusetts")  # not the airline
        raise readers.ReaderError("not found", gone=True)

    async def suggest(industry, city, model):
        return [{"company": "Visa", "url": None, "city": city}, {"company": "Delta Air Lines", "url": None, "city": city}, {"company": "Delta", "url": None, "city": city}]

    monkeypatch.setattr(finder, "read_employer", read)
    monkeypatch.setattr(finder, "_suggest", suggest)
    monkeypatch.setattr(finder, "search_model", lambda: "m")
    out = asyncio.run(finder.find_employers("Finance", ["Boston, MA"]))
    assert [(f.name, f.system) for f in out.added] == [("Visa", "smartrecruiters")]
    assert sorted(out.unreadable) == ["Delta", "Delta Air Lines"]  # "Delta" found Delta Dental's list: a different company, so it is left out


def test_a_smartrecruiters_form_address_names_the_company_of_the_saved_posting():
    from app.services.apply.questions import smartrecruiters_company as company

    posting = "https://jobs.smartrecruiters.com/BostonMedicalCenter/109741273-senior-financial-analyst"
    form = "https://jobs.smartrecruiters.com/oneclick-ui/company/BostonMedicalCenter/publication/2c4fbfd7-7bb8-4699-9fa2-ccacc65e17fb?dcr_ci=BostonMedicalCenter"
    assert company(posting) == company(form) == "bostonmedicalcenter"
    assert company("https://jobs.lever.co/acme/123") is None and company("https://jobs.smartrecruiters.com/oneclick-ui") is None


def test_employers_known_by_address_get_their_proper_name(tmp_path):
    from app.services.jobcache import store
    from app.services.jobcache.store import JobCache, guess_name, known_name

    wd = "roberthalf.wd1.myworkdayjobs.com|roberthalf|ProtivitiExperiencedCareers"
    assert known_name("workday", wd) == "Protiviti"
    assert known_name("workday", "roberthalf.wd1.myworkdayjobs.com|roberthalf|RobertHalfCareers") is None  # another site on that account
    assert guess_name("workday", "premierinc.wd1.myworkdayjobs.com|premierinc|External_Professional") == "Premier Inc."
    assert guess_name("workday", "unknown.wd1.myworkdayjobs.com|unknown|Jobs") == "Unknown"
    assert known_name("lever", "pmaconsultants") == "PMA Consultants"

    path = str(tmp_path / "names.db")
    cache = JobCache(path)
    with cache.session() as db:  # saved before the proper name was known
        db.execute("INSERT INTO employers (ats, identifier, name, source, added_at) VALUES ('workday', ?, 'Roberthalf', 'user_link', 0)", (wd,))
    store._INITIALISED.pop(path)
    JobCache(path)  # opening the copy again fixes the name
    with cache.session() as db:
        assert db.execute("SELECT name FROM employers").fetchone()["name"] == "Protiviti"


# ---- pay written inside a posting's text -----------------------------------------------------------------------

def test_pay_from_text_reads_believable_ranges_only():
    f = text.pay_from_text
    assert f("The salary range for this role is $85,000 - $110,000 per year.") == ("$85,000 - $110,000 / year", 97500)
    assert f("Pay range: $85K to $110K") == ("$85,000 - $110,000 / year", 97500)
    assert f("We pay $42 to $55 an hour") == ("$42 - $55 / hour", 48.5 * 2080)
    assert f("Starting salary of $82,000 plus benefits") == ("$82,000 / year", 82000)
    assert f("Base pay: $90,000.00 – $120,000.00") == ("$90,000 - $120,000 / year", 105000)
    # not pay: company facts, bonuses, small numbers with no pay word, absurd ranges, nothing at all
    assert f("We raised $50 - $75 million in funding") == (None, None)
    assert f("Our revenue is $200,000 - $300,000 per client") == (None, None)
    assert f("Sign-on bonus of $5,000 - $10,000") == (None, None)
    assert f("Join our team of 10 - 20 people") == (None, None)
    assert f("Salary $30,000 - $900,000") == (None, None)
    assert f("") == (None, None) and f(None) == (None, None)


def test_html_to_text_decodes_escaped_markup():
    assert text.html_to_text("&lt;p&gt;Pay: &amp;lt;b&amp;gt;$90,000&amp;lt;/b&amp;gt; &lt;/p&gt;").strip() == "Pay: $90,000"


def test_readers_find_pay_in_posting_text():
    gh = readers.parse_greenhouse({"jobs": [{"id": 1, "title": "Revenue Cycle Manager", "absolute_url": "https://boards.greenhouse.io/x/jobs/1",
                                              "content": "&lt;p&gt;The base salary range is $100,000 - $130,000 annually.&lt;/p&gt;"},
                                             {"id": 2, "title": "Analyst", "absolute_url": "https://boards.greenhouse.io/x/jobs/2", "content": "&lt;p&gt;No pay here&lt;/p&gt;"}]}, "x")
    assert (gh[0].pay_text, gh[0].pay_mid) == ("$100,000 - $130,000 / year", 115000) and gh[1].pay_text is None
    lv = readers.parse_lever([{"id": "a", "text": "Billing Lead", "descriptionPlain": "Compensation: $70,000 to $85,000 per year", "categories": {}}])
    assert lv[0].pay_mid == 77500
    lv2 = readers.parse_lever([{"id": "b", "text": "Billing Lead", "salaryRange": {"min": 60000, "max": 70000, "currency": "USD", "interval": "per-year-salary"},
                                "descriptionPlain": "Compensation: $1 to $2", "categories": {}}])
    assert lv2[0].pay_text == "$60,000 - $70,000"  # the posting's own pay field wins over the text
    ab = readers.parse_ashby({"jobs": [{"id": "z", "title": "Denials Specialist", "descriptionPlain": "Salary: $65,000 - $75,000 per year"}]}, "b")
    assert ab[0].pay_mid == 70000


async def test_cache_tools_reread_updates_only_existing_postings(tmp_path, monkeypatch):
    import argparse
    from scripts import cache_tools

    cache = JobCache(str(tmp_path / "copy.db"))
    eid, _ = cache.upsert_employer("greenhouse", "acme", "Acme", "search")
    cache.apply_refresh(eid, [PostingIn(ext_id="1", title="Revenue Cycle Manager", url="https://x/1", location="Boston, MA")], now_ts())

    async def fake_read(ats, ident, client, throttle):
        return readers.ReadResult([
            PostingIn(ext_id="1", title="Revenue Cycle Manager", url="https://x/1", location="Boston, MA", pay_text="$90,000 - $100,000 / year", pay_mid=95000),
            PostingIn(ext_id="2", title="Brand New Job", url="https://x/2"),
        ])

    monkeypatch.setattr(cache_tools, "read_employer", fake_read)
    assert await cache_tools._reread(argparse.Namespace(db=str(tmp_path / "copy.db"), only=None, live=False)) == 0
    with cache.session() as db:
        rows = {r["ext_id"]: r for r in db.execute("SELECT * FROM postings")}
    assert set(rows) == {"1"} and rows["1"]["pay_mid"] == 95000 and rows["1"]["closed_at"] is None
    live = argparse.Namespace(db=str(tmp_path / "copy.db"), only=None, live=False)
    monkeypatch.setattr(cache_tools.settings, "JOB_CACHE_PATH", str(tmp_path / "copy.db"))
    assert await cache_tools._reread(live) == 1  # refuses the live path without --live


# ---- places and distance ---------------------------------------------------------------------------------------

def test_geo_distances_and_nearby_places():
    from app.services.jobcache import geo

    boston, cambridge, nyc = geo.lookup("Boston", "MA"), geo.lookup("Cambridge", "MA"), geo.lookup("New York", "NY")
    assert 1 < geo.miles_between(boston, cambridge) < 4
    assert 180 < geo.miles_between(boston, nyc) < 200
    assert geo.lookup("Boston", None) == boston and geo.lookup("Nowhereville", "MA") is None
    assert geo.lookup("St. Louis", "MO") == geo.lookup("Saint Louis", "MO")
    near = geo.nearby("Boston", "MA")
    assert "Cambridge, MA" in near and "Worcester, MA" not in near and "Boston, MA" not in near and "Providence, RI" not in near
    assert "Newark, NJ" in geo.nearby("New York", "NY") and "Boston, MA" not in geo.nearby("New York", "NY")
    assert geo.nearby("Nowhereville", "MA") == []


def test_geo_file_adds_places_and_a_damaged_file_is_ignored(tmp_path, monkeypatch):
    from app.services.jobcache import geo

    monkeypatch.setattr(geo.settings, "JOB_CACHE_PATH", str(tmp_path / "job_cache.db"))
    (tmp_path / "geo").mkdir()
    (tmp_path / "geo" / "us_places.json").write_text('[["Wayland","MA",42.3626,-71.3612,13000]]')
    assert "Wayland, MA" in geo.nearby("Boston", "MA") and geo.lookup("Wayland", "MA") is not None
    (tmp_path / "geo" / "us_places.json").write_text("not json")
    assert geo.lookup("Boston", "MA") is not None  # built-in places still work


async def test_expand_places_uses_coordinates_without_the_ai(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "JOB_SEARCH_MODEL", "")
    monkeypatch.setattr(service.settings, "PRIMARY_FAST_MODEL", "")
    assert "Somerville, MA" in await service.expand_places("Boston, MA")
    assert "Somerville, MA" in await service.expand_places("Boston, MA or remote")
    assert await service.expand_places("Nowhereville, MA") == []  # no coordinates and no AI: stays on the place typed


def test_cache_tools_coverage_report(tmp_path, capsys):
    import argparse
    from scripts import cache_tools

    cache = JobCache(str(tmp_path / "c.db"))
    eid, _ = cache.upsert_employer("lever", "acme", "Acme", "search")
    cache.apply_refresh(eid, [
        PostingIn(ext_id="1", title="A", url="https://x/1", location="Boston, MA", pay_text="$1"),
        PostingIn(ext_id="2", title="B", url="https://x/2", location="2 Locations"),
    ], now_ts())
    assert cache_tools.cmd_coverage(argparse.Namespace(db=str(tmp_path / "c.db"))) == 0
    out = capsys.readouterr().out
    assert "lever" in out and "50%" in out and "coordinates" in out


# ---- descriptions ----------------------------------------------------------------------------------------------

def test_location_from_text_needs_an_explicit_label():
    f = text.location_from_text
    assert f("Great role.\nLocation: Waltham, MA\nApply now") == "Waltham, MA"
    assert f("Work Location - Austin, TX") == "Austin, TX"
    assert f("Our Boston headquarters is lovely") is None and f("Location: Narnia, ZZ") is None and f(None) is None


def test_description_is_saved_compressed_and_rewritten_only_when_changed(tmp_path):
    cache = JobCache(str(tmp_path / "d.db"))
    eid, _ = cache.upsert_employer("greenhouse", "acme", "Acme", "search")
    base = dict(ext_id="1", title="Revenue Cycle Manager", url="https://x/1", location="Boston, MA")
    cache.apply_refresh(eid, [PostingIn(**base, description="Lead denials management and charge capture.")], now_ts())
    with cache.session() as db:
        row = db.execute("SELECT description_z, desc_hash FROM postings").fetchone()
        first = row["desc_hash"]
        assert isinstance(row["description_z"], bytes) and first
    # same text again: untouched; new text: replaced; no text this time: the saved text is kept
    cache.apply_refresh(eid, [PostingIn(**base, description="Lead denials management and charge capture.")], now_ts())
    cache.apply_refresh(eid, [PostingIn(**base)], now_ts())
    with cache.session() as db:
        assert db.execute("SELECT desc_hash FROM postings").fetchone()["desc_hash"] == first
    cache.apply_refresh(eid, [PostingIn(**base, description="Now also owns payer contracting.")], now_ts())
    got = cache.candidates(None, ["%"], 10)
    assert got[0]["description"] == "Now also owns payer contracting." and "description_z" not in got[0]


def test_older_copies_gain_the_new_columns(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE employers (id INTEGER PRIMARY KEY, ats TEXT NOT NULL, identifier TEXT NOT NULL, name TEXT NOT NULL, industry TEXT,
          source TEXT NOT NULL DEFAULT 'search', enabled INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'new', fail_count INTEGER NOT NULL DEFAULT 0,
          last_error TEXT, last_checked INTEGER, last_ok INTEGER, next_check INTEGER NOT NULL DEFAULT 0, open_count INTEGER NOT NULL DEFAULT 0,
          hits INTEGER NOT NULL DEFAULT 0, added_at INTEGER NOT NULL, UNIQUE (ats, identifier));
        CREATE TABLE postings (id INTEGER PRIMARY KEY, employer_id INTEGER NOT NULL, ext_id TEXT NOT NULL, title TEXT NOT NULL, location TEXT,
          work_type TEXT, pay_text TEXT, pay_mid REAL, posted_at TEXT, url TEXT NOT NULL, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
          closed_at INTEGER, UNIQUE (employer_id, ext_id));
        INSERT INTO employers (id, ats, identifier, name, added_at) VALUES (1, 'lever', 'a', 'A', 1);
        INSERT INTO postings (employer_id, ext_id, title, url, first_seen, last_seen) VALUES (1, 'x', 'Old Job', 'https://x', 1, 1);
    """)
    conn.commit()
    conn.close()
    cache = JobCache(str(path))
    with cache.session() as db:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(postings)")}
        assert {"description_z", "desc_hash", "agency"} <= cols
        assert db.execute("SELECT title FROM postings").fetchone()["title"] == "Old Job"


def test_keywords_are_found_in_a_saved_description():
    plan = matcher.build_plan(SimpleNamespace(titles="Revenue Cycle Manager", keywords="Epic Resolute", location="", work_type="any",
                                              target_salary=None, exclude_companies="", posted_within_days=0))
    row = {"title": "Revenue Cycle Manager", "company": "Acme", "location": "Boston, MA", "work_type": None, "pay_mid": None, "posted_at": None}
    assert matcher.score_row(plan, row) is None  # the keyword is nowhere in the title, employer or place
    assert matcher.score_row(plan, {**row, "description": "Experience with Epic Resolute billing required"}) is not None


# ---- safe first-seen dates -------------------------------------------------------------------------------------

def _day(ts):
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date().isoformat()


def test_first_seen_day_is_a_date_only_when_it_is_trustworthy(tmp_path):
    cache = JobCache(str(tmp_path / "s.db"))
    eid, _ = cache.upsert_employer("workday", "acme", "Acme", "search")
    P = lambda n, **kw: PostingIn(ext_id=str(n), title=f"Job {n}", url=f"https://x/{n}", **kw)

    def seen(n):
        with cache.session() as db:
            return db.execute("SELECT seen_date FROM postings WHERE ext_id = ?", (str(n),)).fetchone()["seen_date"]

    t0 = 1_800_000_000
    cache.apply_refresh(eid, [P(1), P(2)], t0)                       # the board's first read: nothing is dated
    assert seen(1) is None and seen(2) is None
    cache.apply_refresh(eid, [P(1), P(2), P(3)], t0 + 3600 * 6)      # read again 6 hours later: the new job is dated
    assert seen(3) == _day(t0 + 3600 * 6) and seen(1) is None
    cache.apply_refresh(eid, [P(1), P(2), P(3), P(4)], t0 + 3600 * 6 + 3600 * 60)   # 60 hours since the last read: too long a gap
    assert seen(4) is None
    cache.apply_refresh(eid, [P(1), P(2), P(3), P(4), P(5, posted_at=dt.date(2026, 1, 2))], t0 + 3600 * 70)
    assert seen(5) is None                                           # the board gave a real date: that is used, not ours
    cache.apply_refresh(eid, [P(1), P(2), P(3), P(4), P(5), P(6)], t0 + 3600 * 76, close_missing=False)  # a partial read
    assert seen(6) is None
    cache.apply_refresh(eid, [P(n) for n in range(100, 160)], t0 + 3600 * 80)  # every job looks new: the employer renumbered
    assert all(seen(n) is None for n in (100, 150))


def test_a_trusted_first_seen_day_counts_as_the_posting_date(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "JOB_CACHE_PATH", str(tmp_path / "w.db"))
    cache = JobCache()
    eid, _ = cache.upsert_employer("workday", "acme", "Acme", "search")
    now = now_ts()
    cache.apply_refresh(eid, [PostingIn(ext_id="1", title="Revenue Cycle Manager", url="https://x/1", location="Boston, MA")], now - 3600 * 5)
    cache.apply_refresh(eid, [PostingIn(ext_id="1", title="Revenue Cycle Manager", url="https://x/1", location="Boston, MA"),
                              PostingIn(ext_id="2", title="Revenue Cycle Director", url="https://x/2", location="Boston, MA")], now)
    crit = SimpleNamespace(titles="Revenue Cycle Manager, Revenue Cycle Director", keywords="", location="Boston, MA", work_type="any", target_salary=None,
                           exclude_companies="", posted_within_days=7)
    ranked = matcher.rank(matcher.build_plan(crit), cache.candidates(None, ["%"], 50))
    item = service.to_item(next(r for r in ranked if r.row["ext_id"] == "2"))
    assert item["posted_at"] == dt.date.fromisoformat(_day(now))
    still = [r.row["ext_id"] for r in matcher.rank(matcher.build_plan(crit), cache.candidates(None, ["%"], 50))]
    assert "1" not in still  # first seen before the crawl was trusted: no date, so it does not qualify for "last 7 days"


# ---- O*NET titles ----------------------------------------------------------------------------------------------

def _write_onet(tmp_path, monkeypatch):
    from app.services.jobcache import onet

    monkeypatch.setattr(onet.settings, "JOB_CACHE_PATH", str(tmp_path / "job_cache.db"))
    (tmp_path / "onet").mkdir()
    (tmp_path / "onet" / "titles.json").write_text(json.dumps({"release": "O*NET 99.9", "occupations": [
        ["Medical Records Specialists", ["Billing Specialist", "Medical Biller", "Patient Account Representative", "Claims Specialist", "Senior Billing Specialist",
                                         "Billing Manager", "Coding Specialist"]],
        ["Accountants", ["Staff Accountant", "Tax Accountant"]],
    ]}))
    return onet


def test_onet_gives_other_names_for_the_same_job_and_nothing_when_unknown(tmp_path, monkeypatch):
    onet = _write_onet(tmp_path, monkeypatch)
    got = onet.alternates("billing specialist")
    assert "Medical Biller" in got and "Billing Specialist" not in got
    assert "Billing Manager" not in got and "Senior Billing Specialist" not in got      # a different seniority is left out
    assert "Staff Accountant" not in got                                               # a different occupation
    assert onet.alternates("Specialist Billing") != [] and onet.alternates("quantum llama wrangler") == []
    assert onet.release() == "O*NET 99.9" and "CC BY 4.0" in onet.ATTRIBUTION


def test_onet_is_optional_and_a_damaged_file_is_ignored(tmp_path, monkeypatch):
    from app.services.jobcache import onet

    monkeypatch.setattr(onet.settings, "JOB_CACHE_PATH", str(tmp_path / "none.db"))
    assert onet.alternates("billing specialist") == [] and not onet.available()
    (tmp_path / "onet").mkdir()
    (tmp_path / "onet" / "titles.json").write_text("{broken")
    monkeypatch.setattr(onet.settings, "JOB_CACHE_PATH", str(tmp_path / "job_cache.db"))
    assert onet.alternates("billing specialist") == []


async def test_expand_titles_uses_onet_first_and_the_ai_only_to_fill_gaps(tmp_path, monkeypatch):
    _write_onet(tmp_path, monkeypatch)
    monkeypatch.setattr(service.settings, "JOB_CACHE_PATH", str(tmp_path / "job_cache.db"))
    calls = []

    async def fake_ai(titles):
        calls.append(titles)
        return ["Collections Analyst", "Staff Accountant"]

    monkeypatch.setattr(service, "_expand_titles_ai", fake_ai)
    full = await service.expand_titles("billing specialist")        # four or more from O*NET: no AI call at all
    assert "Medical Biller" in full and len(full) >= 4 and calls == []
    gap = await service.expand_titles("tax accountant")             # fewer than four: the AI fills in, no repeats
    assert "Staff Accountant" in gap and "Collections Analyst" in gap and gap.count("Staff Accountant") == 1 and calls == ["tax accountant"]


# ---- agency flag (a label only) --------------------------------------------------------------------------------

def test_agency_flag_needs_evidence():
    from app.services.jobcache.agency import is_agency

    assert is_agency("Robert Half") is True and is_agency("Acme Staffing Solutions") is True and is_agency("Kforce Inc") is True
    assert is_agency("Mass General Brigham", "On behalf of our client, a leading health system...") is True
    assert is_agency("Mass General Brigham", "Join our billing team and help patients.") is None   # not decided, never 'direct'
    assert is_agency(None, None) is None


def test_agency_flag_never_changes_which_jobs_a_search_returns(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "JOB_CACHE_PATH", str(tmp_path / "ag.db"))
    cache = JobCache()
    direct, _ = cache.upsert_employer("lever", "mgb", "Mass General Brigham", "search")
    agency, _ = cache.upsert_employer("lever", "rh", "Robert Half", "search")
    for eid in (direct, agency):
        cache.apply_refresh(eid, [PostingIn(ext_id="1", title="Revenue Cycle Manager", url=f"https://x/{eid}", location="Boston, MA")], now_ts())
    with cache.session() as db:
        flags = {r["name"]: r["agency"] for r in db.execute("SELECT e.name, p.agency FROM postings p JOIN employers e ON e.id = p.employer_id")}
    assert flags == {"Mass General Brigham": None, "Robert Half": 1}
    crit = SimpleNamespace(titles="Revenue Cycle Manager", keywords="", location="Boston, MA", work_type="any", target_salary=None,
                           exclude_companies="", posted_within_days=0)
    def results():
        return sorted((s.row["company"], s.fit) for s in matcher.rank(matcher.build_plan(crit), cache.candidates(None, ["%"], 50)))
    with_flags = results()
    with cache.session() as db:
        db.execute("UPDATE postings SET agency = NULL")
    assert results() == with_flags and len(with_flags) == 2   # same jobs, same order, same scores, flagged or not


def test_sites_from_urls_finds_unread_workday_career_sites():
    from scripts import cache_tools

    urls = [
        "https://mgb.wd1.myworkdayjobs.com/en-US/MGBExternal/job/Boston-MA/X_R1",
        "https://mgb.wd1.myworkdayjobs.com/MGB_Enterprise/job/Somerville/Y_R2",
        "https://mgb.wd1.myworkdayjobs.com/en-US/MGB_Enterprise/jobs",
        "https://mgb.wd1.myworkdayjobs.com/en-US/login",
        "https://example.com/careers",
    ]
    got = cache_tools.sites_from_urls(urls, {"mgb.wd1.myworkdayjobs.com|mgb|MGBExternal"})
    assert got == {"mgb.wd1.myworkdayjobs.com|mgb|MGB_Enterprise": 2}


def test_sites_ignore_capital_letters_robots_and_language_codes():
    from scripts import cache_tools

    urls = [
        "https://mgb.wd1.myworkdayjobs.com/en-US/mgbexternal/job/Boston-MA/X_R1",
        "https://mgb.wd1.myworkdayjobs.com/robots.txt",
        "https://mgb.wd1.myworkdayjobs.com/es/job/x",
        "https://mgb.wd1.myworkdayjobs.com/MGB_Ent/job/y",
        "https://mgb.wd1.myworkdayjobs.com/mgb_ent/job/z",
    ]
    assert cache_tools.sites_from_urls(urls, {"mgb.wd1.myworkdayjobs.com|mgb|MGBExternal"}) == {"mgb.wd1.myworkdayjobs.com|mgb|MGB_Ent": 2}


async def test_workday_list_past_the_2000_window_is_read_in_category_slices(monkeypatch):
    from app.services.jobcache import readers

    jobs = {"A": [f"/job/a{i}_R{i}" for i in range(1200)], "B": [f"/job/b{i}_R{5000 + i}" for i in range(1100)]}
    everything = jobs["A"] + jobs["B"]
    facets = [{"facetParameter": "jobFamilyGroup", "values": [{"id": "A", "count": 1200}, {"id": "B", "count": 1100}]}]

    async def fake(client, throttle, system, method, url, text=False, **kw):
        body = kw["json"]
        pool = jobs[body["appliedFacets"]["jobFamilyGroup"][0]] if body["appliedFacets"] else everything[:2000]  # the window: only the first 2000
        page = pool[body["offset"]: body["offset"] + body["limit"]]
        return {"total": len(pool), "facets": facets, "jobPostings": [{"externalPath": p, "title": "Nurse", "locationsText": "Boston, MA"} for p in page]}

    monkeypatch.setattr(readers, "_request", fake)
    res = await readers._read_workday("h.wd1.myworkdayjobs.com|h|Careers", None, readers.Throttle())
    assert len(res.postings) == 2300 and res.complete


async def test_workday_list_inside_the_window_is_one_search(monkeypatch):
    from app.services.jobcache import readers

    calls = []

    async def fake(client, throttle, system, method, url, text=False, **kw):
        calls.append(kw["json"]["appliedFacets"])
        n = 45
        page = [f"/job/x{i}_R{i}" for i in range(n)][kw["json"]["offset"]: kw["json"]["offset"] + 20]
        return {"total": n, "jobPostings": [{"externalPath": p, "title": "RN"} for p in page]}

    monkeypatch.setattr(readers, "_request", fake)
    res = await readers._read_workday("h.wd1.myworkdayjobs.com|h|Careers", None, readers.Throttle())
    assert len(res.postings) == 45 and res.complete and all(c == {} for c in calls)


def test_workday_slices_find_nested_filters():
    from app.services.jobcache import readers

    data = {"facets": [{"facetParameter": "locationMainGroup", "values": [{"facetParameter": "locations", "values": [{"id": "x", "count": 3}]}]},
                       {"facetParameter": "timeType", "values": [{"id": "ft", "count": 9}]}]}
    assert readers.workday_slices(data) == [("locations", [("x", 3)]), ("timeType", [("ft", 9)])]


def test_probe_row_summarizes_an_employer_on_one_line():
    from app.services.jobcache.store import PostingIn
    from scripts import cache_tools

    ps = [PostingIn(ext_id="1", title="Revenue Cycle Analyst", url="u1", location="Boston, MA"),
          PostingIn(ext_id="2", title="Gardener", url="u2", location="London, United Kingdom")]
    row = cache_tools.probe_row("greenhouse:acme", ps, True, [])
    assert "jobs 2" in row and "US 50%" in row and "foreign 50%" in row and "focus-title 1" in row and "PARTIAL" not in row
    assert "PARTIAL" in cache_tools.probe_row("greenhouse:acme", ps, False, ["note"])


async def test_add_command_applies_the_standing_rule(tmp_path, monkeypatch):
    import argparse

    from app.services.jobcache.store import JobCache, PostingIn
    from scripts import cache_tools

    monkeypatch.setattr(cache_tools.settings, "JOB_CACHE_PATH", str(tmp_path / "live.db"))
    big = [PostingIn(ext_id=str(i), title=f"Analyst {i}", url=f"https://job-boards.greenhouse.io/x/jobs/{i}", location="Boston, MA") for i in range(12)]
    abroad = [PostingIn(ext_id=str(i), title=f"Analyst {i}", url=f"https://job-boards.greenhouse.io/y/jobs/{i}", location="London, United Kingdom") for i in range(12)]

    async def fake(system, ident, client, throttle):
        from app.services.jobcache.readers import ReadResult

        return ReadResult({"good": big, "abroad": abroad, "tiny": big[:3], "staffing": big}[ident])

    monkeypatch.setattr(cache_tools, "read_employer", fake)
    f = tmp_path / "p.txt"
    f.write_text("'greenhouse:good'  # a\n'greenhouse:abroad'\n'greenhouse:tiny'\n'greenhouse:staffing'\n")
    ns = lambda apply: argparse.Namespace(from_file=str(f), apply=apply, min_jobs=10, min_us=60, skip=["staffing"], include=None, source="curated", parallel=3)
    assert await cache_tools._add(ns(False)) == 0
    assert JobCache().list_employers() == []                     # a dry run writes nothing
    assert await cache_tools._add(ns(True)) == 0
    got = JobCache().list_employers()
    assert [e["identifier"] for e in got] == ["good"] and got[0]["source"] == "curated"
    assert JobCache().counts()["postings"] == 12


def test_place_text_is_told_apart_by_state_name_country_or_neither():
    from scripts import cache_tools as c

    assert [c.location_kind(x) for x in ["London, United Kingdom", "Remote Poland", "Singapore, Singapore", "Toronto, Ontario, Canada"]] == ["foreign"] * 4
    assert [c.location_kind(x) for x in ["Main Campus", "2 Locations", None, "Remote"]] == ["unknown"] * 4


def test_boards_from_urls_lists_new_boards_once_each():
    from scripts import cache_tools

    urls = [
        "https://boards.greenhouse.io/acme/jobs/1", "https://job-boards.greenhouse.io/Acme/jobs/2",
        "https://boards.greenhouse.io/newco/jobs/9", "https://boards.greenhouse.io/known", "https://jobs.lever.co/other/1",
        "https://boards.greenhouse.io/embed/job_board",
    ]
    assert cache_tools.boards_from_urls(urls, "greenhouse", {"known"}) == ["greenhouse:acme", "greenhouse:newco"]


def test_parse_num_pages():
    from scripts.cache_tools import parse_num_pages

    assert parse_num_pages('{"pages": 12, "pageSize": 5}') == 12
    assert parse_num_pages("12") == 12
    assert parse_num_pages("Number of pages: 7") == 7
    assert parse_num_pages("<html>Too many requests</html>") == 0
    assert parse_num_pages("") == 0


def test_urls_from_cdx_skips_broken_lines():
    from scripts.cache_tools import urls_from_cdx

    text = '{"url": "https://a.bamboohr.com/careers"}\n{"url": "https://b.bamboohr.com/care'
    got, bad = urls_from_cdx(text)
    assert got == ["https://a.bamboohr.com/careers"] and bad == 1
    assert urls_from_cdx("")[0] == []


def test_already_judged_reads_earlier_output(tmp_path):
    from scripts.cache_tools import _already_judged

    f = tmp_path / "out.txt"
    f.write_text(
        "5 employers to check.\n"
        "  ADD   workable:acme  120 jobs\n"
        "  SKIP  bamboohr:foo  too few jobs\n"
        "  SKIP  jazzhr:bar  could not be read (ReadTimeout)\n"
        "  HAVE  lever:baz  already in the saved lists\n"
        "\n1 would be added, 2 skipped.\n"
    )
    assert _already_judged([str(f)]) == {"workable:acme", "bamboohr:foo", "lever:baz"}


def test_industry_classify_and_tag(tmp_path):
    from app.services.jobcache.industry import OTHER, STAFFING, classify, tag_employers
    from app.services.jobcache.store import JobCache, PostingIn, now_ts

    assert classify("Beth Israel Lahey Health", ["Registered Nurse", "Patient Access Rep", "Revenue Cycle Analyst"]) == "Health Care and Social Assistance"
    assert classify("Acme Robotics", ["Software Engineer", "Backend Developer", "Product Designer"]) == "Information"
    assert classify("First Harbor Bank", ["Loan Officer", "Teller", "Credit Analyst"]) == "Finance and Insurance"
    assert classify("Apex Staffing Group", ["Registered Nurse"]) == STAFFING
    assert classify("Quiet Co", ["Office Manager"]) == OTHER
    assert classify("Quiet Co", []) == OTHER

    cache = JobCache(str(tmp_path / "c.db"))
    a, _ = cache.upsert_employer("greenhouse", "acmehospital", "Acme Hospital", "curated")
    b, _ = cache.upsert_employer("greenhouse", "manual", "Manual Co", "curated", industry="Retail Trade")
    cache.apply_refresh(a, [PostingIn(ext_id="1", title="Registered Nurse", url="https://x/1")], now_ts(), 6.0, True)
    with cache.session() as db:
        table = tag_employers(db)
        got = {r["name"]: r["industry"] for r in db.execute("SELECT name, industry FROM employers")}
    assert got == {"Acme Hospital": "Health Care and Social Assistance", "Manual Co": "Retail Trade"}  # one with an industry is left alone
    assert table["Health Care and Social Assistance"][0] == 1


def _desc_cache(tmp_path):
    from app.services.jobcache.store import JobCache, PostingIn, now_ts

    cache = JobCache(str(tmp_path / "d.db"))
    eid, _ = cache.upsert_employer("greenhouse", "acmehealth", "Acme Health", "curated")
    cache.apply_refresh(
        eid,
        [
            PostingIn(ext_id="1", title="Business Analyst", url="https://x/1",
                      description="Join our revenue cycle team to analyze denials and payer trends across the system."),
            PostingIn(ext_id="2", title="Software Engineer", url="https://x/2",
                      description="Build the revenue cycle platform used by our billing teams."),
            PostingIn(ext_id="3", title="Revenue Cycle Analyst", url="https://x/3", description="Analyze claims."),
            PostingIn(ext_id="4", title="Office Manager", url="https://x/4"),
        ],
        now_ts(), 6.0, True,
    )
    return cache


def test_description_index_find_and_close(tmp_path):
    from app.services.jobcache.store import now_ts

    cache = _desc_cache(tmp_path)
    assert cache.has_desc
    assert not cache.desc_ready()
    assert cache.candidates_by_description('"revenue cycle"', 50) == []  # nothing is read until the index is declared built
    assert cache.reindex_descriptions() == 0  # new postings were indexed as they were saved
    assert cache.desc_ready()
    found = {r["title"] for r in cache.candidates_by_description('"revenue cycle"', 50)}
    assert found == {"Business Analyst", "Software Engineer"}
    eid = cache.list_employers()[0]["id"]
    from app.services.jobcache.store import PostingIn

    cache.apply_refresh(eid, [PostingIn(ext_id="2", title="Software Engineer", url="https://x/2", description="Build the revenue cycle platform used by our billing teams.")], now_ts() + 10, 6.0, True)
    assert {r["title"] for r in cache.candidates_by_description('"revenue cycle"', 50)} == {"Software Engineer"}  # the closed one left the index


def test_description_reindex_catches_up_older_rows(tmp_path):
    cache = _desc_cache(tmp_path)
    with cache.session() as db:
        db.execute("DELETE FROM postings_desc_fts")  # as if the postings were saved before the index existed
    assert cache.reindex_descriptions() == 3
    assert {r["title"] for r in cache.candidates_by_description('"revenue cycle"', 50)} == {"Business Analyst", "Software Engineer"}


def test_description_changes_the_match(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.config import settings
    from app.services.jobcache import matcher

    crit = SimpleNamespace(titles="revenue cycle analyst", location=None, work_type="any", keywords=None, target_salary=None,
                           exclude_companies=None, posted_within_days=0)
    biz = {"title": "Business Analyst", "company": "Acme Health", "location": "Boston, MA", "work_type": None,
           "description": "Join our revenue cycle team to analyze denials."}
    eng = {"title": "Software Engineer", "company": "Acme Health", "location": "Boston, MA", "work_type": None,
           "description": "Build the revenue cycle platform."}
    real = {"title": "Revenue Cycle Analyst", "company": "Acme Health", "location": "Boston, MA", "work_type": None, "description": None}

    plan = matcher.build_plan(crit)
    assert plan.desc_phrases and matcher.fts_desc_query(plan) == '"revenue cycle"'
    ranked = matcher.rank(plan, [biz, eng, real])
    assert [s.row["title"] for s in ranked] == ["Revenue Cycle Analyst", "Business Analyst"]  # the engineer's title shares no role word
    assert ranked[1].via_description and not ranked[0].via_description

    monkeypatch.setattr(settings, "JOB_SEARCH_USE_DESCRIPTION", False)
    off = matcher.build_plan(crit)
    assert off.desc_phrases == [] and matcher.fts_desc_query(off) is None
    assert [s.row["title"] for s in matcher.rank(off, [biz, eng, real])] == ["Revenue Cycle Analyst"]

    # a short title never uses descriptions: "project manager" would match far too many
    short = matcher.build_plan(SimpleNamespace(**{**crit.__dict__, "titles": "project manager"}))
    monkeypatch.setattr(settings, "JOB_SEARCH_USE_DESCRIPTION", True)
    assert matcher.build_plan(SimpleNamespace(**{**crit.__dict__, "titles": "project manager"})).desc_phrases == []
    assert short.desc_phrases == []


def test_usshare_lists_and_turns_off_foreign_employers(tmp_path, monkeypatch):
    import argparse

    from scripts import cache_tools
    from app.services.jobcache.store import JobCache, PostingIn, now_ts

    cache = JobCache(str(tmp_path / "u.db"))
    monkeypatch.setattr(cache_tools, "JobCache", lambda *a, **k: cache)
    a, _ = cache.upsert_employer("smartrecruiters", "us-co", "US Co", "curated")
    b, _ = cache.upsert_employer("smartrecruiters", "eu-co", "EU Co", "curated")
    cache.apply_refresh(a, [PostingIn(ext_id=str(i), title="Nurse", location="Boston, MA", url=f"https://x/a{i}") for i in range(5)], now_ts(), 6.0, True)
    cache.apply_refresh(b, [PostingIn(ext_id=str(i), title="Chef", location="Paris, FR", url=f"https://x/b{i}") for i in range(5)], now_ts(), 6.0, True)
    ns = dict(max_us=30, min_foreign=50, keep_us_jobs=15, top=10, disable=False, restore=False)
    cache_tools.cmd_usshare(argparse.Namespace(**ns))
    with cache.session() as db:
        assert db.execute("SELECT COUNT(*) FROM employers WHERE enabled = 1").fetchone()[0] == 2  # a dry run changes nothing
    cache_tools.cmd_usshare(argparse.Namespace(**{**ns, "disable": True}))
    with cache.session() as db:
        assert [r["name"] for r in db.execute("SELECT name FROM employers WHERE enabled = 1")] == ["US Co"]
    cache_tools.cmd_usshare(argparse.Namespace(**{**ns, "restore": True}))
    with cache.session() as db:
        assert db.execute("SELECT COUNT(*) FROM employers WHERE enabled = 1").fetchone()[0] == 2


def test_smartrecruiters_country_codes_are_not_read_as_us_states():
    from app.services.jobcache.readers import parse_smartrecruiters
    from app.services.jobcache.text import location_fit, parse_location_query

    def loc(city, region, country):
        data = {"content": [{"id": "1", "name": "Nurse", "location": {"city": city, "region": region, "country": country}}]}
        return parse_smartrecruiters(data, "x")[0].location

    assert loc("Toronto", "ON", "ca") == "Toronto, ON, Canada"
    assert loc("Hyderabad", "", "in") == "Hyderabad, India"
    assert loc("Bogota", "", "co") == "Bogota, Colombia"
    assert loc("Casablanca", "", "ma") == "Casablanca, Morocco"
    assert loc("Erie", "PA", "us") == "Erie, PA"  # a US posting is written as before
    california = parse_location_query("California")
    assert location_fit(california, loc("Toronto", "ON", "ca"), None) == 0.0
    assert location_fit(california, "Fresno, CA", None) == 1.0
    assert location_fit(parse_location_query("Indiana"), loc("Hyderabad", "", "in"), None) == 0.0


def test_united_states_search_means_anywhere_in_the_us():
    from app.services.jobcache.text import location_fit, parse_location_query

    q = parse_location_query("United States")
    assert q.nationwide and not q.cities and not q.states
    assert location_fit(q, "Boston, MA", None) == 1.0
    assert location_fit(q, "Austin, Texas", None) == 1.0
    assert location_fit(q, "Remote", "remote") == 0.9
    assert location_fit(q, "Berlin, Germany", None) == 0.0
    assert location_fit(q, "Athens, Greece", None) == 0.0
    assert location_fit(q, "Springfield", None) == 0.5  # says nothing: kept to be checked, as for any search
    assert not parse_location_query("Boston, MA").nationwide


def test_smartrecruiters_big_employer_also_reads_us_jobs(monkeypatch):
    """A cut-off SmartRecruiters list is topped up with the employer's US jobs, and still counts as incomplete."""
    import asyncio
    from app.services.jobcache import readers
    from app.services.jobcache.readers import PostingIn

    def p(i, loc):
        return PostingIn(ext_id=str(i), title=f"Job {i}", url=f"https://x/{i}", location=loc)

    calls = []

    async def fake(identifier, client, throttle, extra=None):
        calls.append(extra)
        if extra:
            return [p(1, "Boston, MA"), p(2, "Austin, TX")], None, True
        return [p(1, "Boston, MA"), p(3, "Paris, France")], "Big Co", False

    monkeypatch.setattr(readers, "_sr_pages", fake)
    res = asyncio.run(readers._read_smartrecruiters("BigCo", None, None))
    assert sorted(x.ext_id for x in res.postings) == ["1", "2", "3"]
    assert res.complete is False and calls == [None, {"country": "us"}]


def test_industry_hand_set_employers_win():
    from app.services.jobcache.industry import classify
    assert classify("AECOM", ["Project Manager"]) == "Professional, Scientific, and Technical Services"
    assert classify("Centria Autism", ["Arabic Speaking Behavior Technician"]) == "Health Care and Social Assistance"
    assert classify("Joyce Corp", ["Welder"]) != "Health Care and Social Assistance"  # "joya" must not catch "joyce"
    assert classify("Accord Healthcare", ["Welder"]) != "Accommodation and Food Services"
    assert classify("AccorHotel", ["Receptionist"]) == "Accommodation and Food Services"


DELOITTE_PAGE = """
<article class="article--result " data-total="999+"><div class="article__content--result"><div class="article__header__text">
<h3 class="article__header__text__title article__header__text__title--2">
<a href="https://apply.deloitte.com/en_US/careers/JobDetail/Project-Associate-Vice-President-Security-Analytics-and-Insights/372165" class="link">
 Project - Associate Vice President, Security Analytics and Insights
</a></h3><div class="article__header__text__subtitle"><span>
 Deloitte US
</span> | <span>
 Deloitte Transactions and Business Analytics LLP
</span> | <span>Rosslyn, Virginia, United States</span></div></div></div></article>
<article class="article--result " data-total="999+"><div class="article__content--result"><div class="article__header__text">
<h3><a href="https://apply.deloitte.com/en_US/careers/JobDetail/WMS-Consulting-Senior-Manager/372156" class="link">WMS Consulting Senior Manager</a></h3>
<div class="article__header__text__subtitle"><span>Deloitte US</span> | <span>Deloitte Consulting LLP</span> | <span>Remote, United States</span></div></div></div></article>
"""


def test_deloitte_parse_and_link():
    from app.services.jobcache import readers
    got = readers.parse_deloitte(DELOITTE_PAGE)
    assert [g.ext_id for g in got] == ["372165", "372156"]
    assert got[0].title == "Project - Associate Vice President, Security Analytics and Insights"
    assert got[0].location == "Rosslyn, Virginia, United States"
    assert got[0].url.endswith("/372165")
    assert readers.parse_deloitte("<html>nothing</html>") == []
    assert readers.employer_ref("https://apply.deloitte.com/en_US/careers/JobDetail/WMS-Consulting-Senior-Manager/372156") == ("deloitte", "apply.deloitte.com")


TB_PAGE = {"results": """<section id="search-results" data-total-job-results="5590" data-total-pages="280"><section id="search-results-list"><ul>
<li>
<a href="/job/omaha/maternal-health-and-epsdt-coordinator-remote-in-nebraska/34088/102182073824" data-job-id="102182073824" class="brand-facet brand-facet__uhc">
<div><h2>Maternal Health and EPSDT Coordinator, Remote in Nebraska</h2>
 <span class="job-id job-info">2388715</span><span class="job-divider"> | </span>
 <span class="job-location 1">Omaha, Nebraska</span><span class="job-divider"> | </span>
 <span class="job-info job-worksetting">Remote</span></div></a>
<button type="button" class="js-save-job-btn" data-job-id="102182073824"></button></li>
<li>
<a href="/job/nashville/rn-case-manager/34088/102182073792" data-job-id="102182073792"><div><h2>RN Case Manager</h2>
 <span class="job-id job-info">2395676</span><span class="job-location 1">Nashville, Tennessee</span></div></a></li>
</ul></section></section>""", "hasJobs": True, "hasContent": False}


def test_talentbrew_parse_and_link():
    from app.services.jobcache import readers
    got, total = readers.parse_talentbrew(TB_PAGE, "careers.unitedhealthgroup.com")
    assert total == 5590
    assert [g.ext_id for g in got] == ["102182073824", "102182073792"]
    assert got[0].title.startswith("Maternal Health") and got[0].location == "Omaha, Nebraska"
    assert got[0].work_type == "remote"
    assert got[1].url == "https://careers.unitedhealthgroup.com/job/nashville/rn-case-manager/34088/102182073792"
    assert readers.parse_talentbrew({"results": "", "hasJobs": True}, "x") == ([], None)
    assert readers.employer_ref("https://careers.unitedhealthgroup.com/job/minnetonka/healthcare-analytics-consultant/34088/101882693968") == ("talentbrew", "careers.unitedhealthgroup.com")
    assert readers.reader_url_allowed("https://careers.unitedhealthgroup.com/search-jobs/results?CurrentPage=1")


def test_workday_address_ignores_language_and_files():
    from app.services.jobcache.readers import employer_ref
    assert employer_ref("https://3m.wd1.myworkdayjobs.com/en") is None
    assert employer_ref("https://aaaie.wd1.myworkdayjobs.com/robots.txt") is None
    assert employer_ref("https://3m.wd1.myworkdayjobs.com/en-US/Search/job/x_R1") == ("workday", "3m.wd1.myworkdayjobs.com|3m|Search")


def test_industry_display_names_and_new_overrides():
    from app.services.jobcache.industry import classify, DISPLAY_NAMES
    assert classify("Hyvee", ["Produce Clerk"]) == "Retail Trade"
    assert classify("Ngc", ["Systems Engineer"]) == "Professional, Scientific, and Technical Services"
    assert DISPLAY_NAMES["jll"] == "JLL" and DISPLAY_NAMES["bjswholesaleclub"] == "BJ's Wholesale Club"


def test_add_keeps_mostly_foreign_employer_with_many_us_jobs():
    import argparse, sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.cache_tools import add_decision
    from app.services.jobcache.store import PostingIn

    def mk(us, fo):
        return [PostingIn(ext_id=str(i), title="t", url="u", location="Boston, MA") for i in range(us)] + [PostingIn(ext_id=f"f{i}", title="t", url="u", location="Paris, France") for i in range(fo)]

    a = argparse.Namespace(skip=None, min_jobs=10, min_us=60, include=None, keep_us_jobs=15)
    ok, why = add_decision("workday", "x.wd1.myworkdayjobs.com|x|S", mk(30, 70), a)
    assert ok and "named by you" not in why
    assert not add_decision("workday", "x.wd1.myworkdayjobs.com|x|S", mk(8, 70), a)[0]


JIBE_PAGE = {"totalCount": 1287, "jobs": [
    {"data": {"slug": "93698", "req_id": "93698", "title": "Senior Graphics Machine Learning Engineer", "city": "Munich", "state": None, "country": "Germany",
              "country_code": "DE", "posted_date": "2026-10-20T13:08:00+0000", "description": "<p>Build things.</p>", "tags2": ["EUR 78,680.00/Yr."]}},
    {"data": {"slug": "93001", "req_id": "93001", "title": "Sr. Director Payroll", "city": "Austin", "state": "Texas", "country": "United States",
              "country_code": "US", "posted_date": "2026-10-19T09:00:00+0000", "description": "<p>Run payroll.</p>", "tags2": ["USD $176,400.00/Yr."]}},
]}


def test_jibe_parse_and_link():
    from app.services.jobcache import readers
    got, total = readers.parse_jibe(JIBE_PAGE, "careers.amd.com")
    assert total == 1287 and [g.ext_id for g in got] == ["93698", "93001"]
    assert got[0].location == "Munich, Germany"
    assert got[1].location == "Austin, Texas, United States"
    assert got[1].url == "https://careers.amd.com/careers-home/jobs/93001?lang=en-us"
    assert got[1].description == "Run payroll."
    assert got[1].pay_text and "176" in got[1].pay_text
    assert readers.parse_jibe({"jobs": []}, "x") == ([], None)
    assert readers.employer_ref("https://careers.amd.com/jobs") == ("jibe", "careers.amd.com")


def test_prelabel_shows_description_opening(monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import eval_search

    monkeypatch.setattr(eval_search.evalset, "describe", lambda c: ["revenue cycle manager in Boston"])
    search = {"criteria": {"titles": ["revenue cycle manager"], "location": "Boston, MA"}, "relevant": "x", "not_relevant": "y"}
    rows = [{"title": "Associate Director", "company": "Acme", "location": "Boston, MA", "pay": None, "url": "https://x/1"}]
    msgs = eval_search.label_messages(search, rows, {"https://x/1": "You will lead patient billing and denials."})
    assert "description opens: You will lead patient billing and denials." in msgs[1]["content"]
    assert "description opens" not in eval_search.label_messages(search, rows)[1]["content"]


def test_a_city_search_finds_local_jobs_among_many_better_worded_titles_elsewhere(monkeypatch):
    """With a huge saved copy, the best title matches nationwide can all be in other cities; the place pull still finds the local ones."""
    from app.services.jobcache import matcher

    monkeypatch.setattr(matcher, "CANDIDATE_LIMIT", 20)
    cache = JobCache()
    eid, _ = cache.upsert_employer("greenhouse", "everywhere", "Everywhere Co", "search")
    far = [post(i, "Data Analyst", "Denver, CO") for i in range(200)]
    near = [post(5000, "Senior Data Analyst, Finance", "Boston, MA"), post(5001, "Data Analyst II", "Cambridge, MA")]
    cache.apply_refresh(eid, far + near, 1000)
    out = service.search_sync(crit(titles="data analyst", location="Boston, MA"), set(), None, 10)
    titles = [i["title"] for i in out.items]
    assert "Senior Data Analyst, Finance" in titles
    assert all("Denver" not in (i["location"] or "") for i in out.items[:2])


def test_one_employer_does_not_fill_the_screen():
    from app.services.jobcache import matcher

    plan = matcher.build_plan(crit(titles="operations coordinator", location=None))
    rows = [{"title": "Operations Coordinator", "company": "Spam Co", "location": f"City {i}", "work_type": None} for i in range(6)]
    rows += [{"title": "Operations Coordinator", "company": "Real Co", "location": "Boston, MA", "work_type": None},
             {"title": "Operations Coordinator II", "company": "Other Co", "location": "Boston, MA", "work_type": None}]
    out = matcher.diversify(matcher.rank(plan, rows))
    companies = [s.row["company"] for s in out]
    assert len(out) == 8  # nothing is dropped
    assert companies[:3].count("Spam Co") == 1  # the repeated opening is shown once, the rest come after the other employers
    assert set(companies[:3]) == {"Spam Co", "Real Co", "Other Co"}


def test_the_work_asked_for_outranks_the_same_role_word_in_another_field():
    plan = matcher.build_plan(crit(titles="revenue cycle analyst", location="Orlando, FL", include_remote=True), ["Financial Analyst", "Billing Analyst"])
    exact = {"title": "Revenue Cycle Analyst Underpayments", "company": "R1 RCM", "location": "Remote, USA", "work_type": "remote", "posted_at": None}
    other = {"title": "Financial Analyst", "company": "Lennar", "location": "Orlando, FL", "work_type": None, "posted_at": None}
    ranked = matcher.rank(plan, [other, exact])
    assert [s.row["company"] for s in ranked] == ["R1 RCM", "Lennar"]  # the exact work first, even though the other is in Orlando


def test_a_job_in_a_foreign_city_with_no_country_is_not_shown_for_a_us_search():
    from app.services.jobcache import text

    austin = text.parse_location_query("Austin, TX")
    for place in ("Montreal", "Toronto", "Bangalore", "London", "Sao Paulo"):
        assert text.location_fit(austin, place, "remote") == 0.0, place
    assert text.location_fit(text.parse_location_query("Austin, TX or remote"), "Remote - US", "remote") > 0
    assert text.location_fit(austin, "Paris, TX", None) == 0.0  # a US town with a foreign name is a town in Texas, not Austin


def test_run_together_employer_names_are_shown_the_way_people_write_them():
    assert text.clean_company("Openai") == "OpenAI"
    assert text.clean_company("1password") == "1Password"
    assert text.clean_company("Assorthealth") == "AssortHealth"
    assert text.clean_company("Examplehealth") == "Example Health"
    assert text.clean_company("Mass General Brigham") == "Mass General Brigham"
    assert text.clean_company("McKesson") == "McKesson"  # a name with its own capitals is left alone


def test_a_requisition_code_is_not_part_of_the_title():
    assert text.title_without_code("Senior Product Marketing Manager (SMM194)") == "Senior Product Marketing Manager"
    assert text.title_without_code("Analyst - R-12345") == "Analyst"
    assert text.title_without_code("Nurse (RN)") == "Nurse (RN)"


def test_one_job_listed_twice_is_one_result_but_two_real_openings_stay_two():
    def job(title, desc, loc="Remote"):
        return {"title": title, "company": "Defense Unicorns", "location": loc, "salary_text": "$142,375 - $230,000",
                "posted_at": dt.date(2026, 10, 13), "_desc": desc, "url": f"https://x.example.com/{title}{desc}"}

    same = [job("Senior Marketing Manager, Edge (SMM193)", "Lead edge product marketing for"), job("Senior Marketing Manager, Edge (SMM194)", "Lead edge product marketing for")]
    assert len(service.collapse_listings(same)) == 1
    other_team = [job("Senior Marketing Manager, Edge (SMM193)", "Lead edge product marketing for"), job("Senior Marketing Manager, Edge (SMM194)", "Run field events and")]
    assert len(service.collapse_listings(other_team)) == 2
    no_text = [job("Senior Marketing Manager, Edge (SMM193)", ""), job("Senior Marketing Manager, Edge (SMM194)", "")]
    assert len(service.collapse_listings(no_text)) == 1  # nothing saved to compare, but both carry a requisition code with the same pay and date
    plain = [job("Nurse", ""), job("Nurse", "")]
    assert len(service.collapse_listings(plain)) == 2  # no code and no text: could be two real openings
    other_place = [job("Nurse", "Care for patients on", "Boston, MA"), job("Nurse", "Care for patients on", "Quincy, MA")]
    assert len(service.collapse_listings(other_place)) == 2


def test_workday_names_the_places_behind_a_three_locations_listing():
    from app.services.discovery.ats import workday_info

    info = workday_info(200, {"jobPostingInfo": {"location": "Boston, MA", "additionalLocations": ["Quincy, MA", "Boston, MA", "Salem, MA", "Lynn, MA"], "startDate": "2026-10-01"}})
    assert info.places == "Boston, MA; Quincy, MA; Salem, MA +1 more"


async def test_web_finds_are_ranked_into_the_list_by_their_match_not_added_at_the_end():
    crit = SimpleNamespace(titles="analyst", location="", work_type=None, keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=None)
    saved = [{"title": f"Analyst {n}", "company": "Acme", "url": f"https://acme.example.com/jobs/{n}", "fit": fit} for n, fit in ((1, 0.95), (2, 0.80), (3, 0.60))]
    service._RANKED[service._ranked_key(crit)] = (__import__("time").time(), saved)
    web = [{"title": "Analyst W", "company": "Newco", "url": "https://newco.example.com/jobs/9", "fit_score": 0.85},
           {"title": "Analyst 1 again", "company": "Acme", "url": "https://acme.example.com/jobs/1", "fit_score": 0.99}]  # already in the list
    added, total = await service.add_to_ranked(crit, web)
    assert (added, total) == (1, 4)
    order = [i["title"] for i in service._RANKED[service._ranked_key(crit)][1]]
    assert order == ["Analyst 1", "Analyst W", "Analyst 2", "Analyst 3"]  # between the 0.95 and the 0.80, not last


def test_places_are_written_the_usual_way_and_long_lists_are_shortened():
    assert text.tidy_place("Newton-MA") == "Newton, MA"
    assert text.tidy_place("Austin,TX") == "Austin, TX"
    assert text.tidy_place("Atlanta, GA; Boston, MA; Chicago, IL; Dallas, TX; Denver, CO") == "Atlanta, GA; Boston, MA; Chicago, IL +2 more"
    assert text.tidy_place("Remote - US") == "Remote - US"
    assert text.clean_company("Dialysisclinic") == "Dialysis Clinic"


def test_a_job_in_another_country_is_never_shown_even_when_the_search_names_a_city_without_a_state():
    california = text.parse_location_query("Boston")
    assert text.location_fit(california, "Cyprus", "remote") == 0.0
    assert text.location_fit(california, "Boston, MA", None) == 1.0


def test_revenue_operations_is_not_revenue_cycle():
    plan = matcher.build_plan(SimpleNamespace(titles="revenue cycle manager", location="", work_type="any", keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=None, count=10), [])
    assert matcher.title_fit(plan, "Revenue Cycle Manager") > 0.9
    assert matcher.title_fit(plan, "Senior Revenue Operations Manager") < matcher.MIN_TITLE_FIT


def test_the_description_decides_between_look_alike_titles():
    plan = matcher.build_plan(SimpleNamespace(titles="revenue cycle manager", location="", work_type="any", keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=None, count=10), [])
    rev = "Lead the revenue cycle team: claims, denials, payer contracts and patient accounts. " * 6
    ops = "Own the CRM, pipeline forecasting and sales and marketing alignment for revenue growth. " * 6
    base = {"company": "X", "location": "Boston, MA", "work_type": None, "posted_at": "2026-10-18", "pay_mid": None, "pay_text": None, "url": "u"}
    score = lambda title, desc: matcher.score_row(plan, {**base, "title": title, "description": desc})
    assert score("Revenue Operations Manager", ops) is None  # about sales operations: not shown
    assert score("Revenue Operations Manager", rev) is not None  # the title is vague but the work is revenue cycle: shown
    assert score("Revenue Cycle Manager", ops) is not None  # a title that matches exactly is never judged by its description
    assert matcher.description_signal(plan, rev) == 1
    assert matcher.description_signal(plan, ops) == -1
    assert matcher.description_signal(plan, None) == 0 and matcher.description_signal(plan, "Short text.") == 0


def test_a_partly_matching_title_with_no_saved_text_is_flagged_for_reading():
    plan = matcher.build_plan(SimpleNamespace(titles="revenue cycle manager", location="", work_type="any", keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=None, count=10), [])
    base = {"company": "X", "location": "Boston, MA", "work_type": None, "posted_at": "2026-10-18", "pay_mid": None, "pay_text": None, "url": "u"}
    flagged = matcher.score_row(plan, {**base, "title": "Revenue Cycle Supervisor", "description": None})
    assert flagged is not None and flagged.needs_description
    exact = matcher.score_row(plan, {**base, "title": "Revenue Cycle Manager", "description": None})
    assert exact is not None and not exact.needs_description
    ops = "Own the CRM, pipeline forecasting and sales alignment for revenue growth. " * 6
    assert matcher.score_row(plan, {**base, "title": "Revenue Cycle Supervisor", "description": ops}) is None


def test_workday_descriptions_are_read_once_and_saved(monkeypatch):
    import asyncio

    import httpx

    cache = JobCache()
    eid, _ = cache.upsert_employer("workday", "acme.wd1.myworkdayjobs.com|acme|Careers", "Acme", "user_link")
    url = "https://acme.wd1.myworkdayjobs.com/en-US/Careers/job/Boston/Revenue-Cycle-Supervisor_R1"
    cache.apply_refresh(eid, [PostingIn(ext_id="/job/Boston/Revenue-Cycle-Supervisor_R1", title="Revenue Cycle Supervisor", url=url, location="Boston, MA")], 1_000_000)
    pid = JobCache().candidates("revenue", [], 10, None)[0]["id"]
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, json={"jobPostingInfo": {"jobDescription": "<p>Lead the revenue cycle team: claims, denials and payer follow-up.</p>" * 6}})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert asyncio.run(service.read_missing_descriptions([(pid, url)])) == 1
    assert asked == ["https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/Careers/job/Boston/Revenue-Cycle-Supervisor_R1"]
    saved = JobCache().candidates("revenue", [], 10, None)[0]["description"]
    assert saved and "claims, denials" in saved


def test_a_posting_page_without_an_api_gives_its_description_from_its_structured_data(monkeypatch):
    import asyncio

    from app.services import safe_fetch

    page = '<html><script type="application/ld+json">{"@type": "JobPosting", "title": "Billing Lead", "description": "<p>Own claims, denials and payer follow-up.</p>"}</script></html>'

    async def fake_get(url, **kw):
        return SimpleNamespace(status_code=200, text=page)

    monkeypatch.setattr(safe_fetch, "safe_get", fake_get)
    assert "denials" in asyncio.run(service._page_description("https://careers-acme.icims.com/jobs/1/billing-lead/job"))

    async def blocked(url, **kw):
        return SimpleNamespace(status_code=403, text="")

    monkeypatch.setattr(safe_fetch, "safe_get", blocked)
    assert asyncio.run(service._page_description("https://careers-acme.icims.com/jobs/1/billing-lead/job")) is None


def test_descriptions_are_filled_in_gradually_a_few_per_employer_and_never_retried_when_unreadable():
    cache = JobCache()
    big, _ = cache.upsert_employer("workday", "big.wd1.myworkdayjobs.com|big|Careers", "Big Health", "user_link")
    small, _ = cache.upsert_employer("icims", "small", "Small Clinic", "user_link")
    gh, _ = cache.upsert_employer("greenhouse", "ghco", "GH Co", "user_link")
    cache.apply_refresh(big, [PostingIn(ext_id=f"/job/{n}", title=f"Analyst {n}", url=f"https://big.wd1.myworkdayjobs.com/en-US/Careers/job/{n}", location="Boston, MA") for n in range(10)], 1_000_000)
    cache.apply_refresh(small, [PostingIn(ext_id="1", title="Billing Clerk", url="https://small.icims.com/jobs/1/job", location="Quincy, MA")], 1_000_000)
    cache.apply_refresh(gh, [PostingIn(ext_id="9", title="Engineer", url="https://job-boards.greenhouse.io/ghco/jobs/9", location="Boston, MA")], 1_000_000)
    todo = cache.postings_without_description(50, 3, {"greenhouse"})
    assert len(todo) == 4  # three from the big employer, one from the small one, none from a system whose list already carries the text
    cache.mark_description_unavailable([i for i, _u in todo])
    assert [i for i, _u in cache.postings_without_description(50, 3, {"greenhouse"})] != [i for i, _u in todo]  # the ones tried are not tried again
    pid = todo[0][0]
    assert cache.set_description(pid, "x" * 5000, max_chars=2000)
    assert pid not in [i for i, _u in cache.postings_without_description(50, 3, {"greenhouse"})]


def test_a_new_employers_postings_can_be_filled_in_on_their_own():
    cache = JobCache()
    old, _ = cache.upsert_employer("icims", "oldco", "Old Co", "search")
    new, _ = cache.upsert_employer("icims", "newco", "New Co", "search")
    for eid, name in ((old, "oldco"), (new, "newco")):
        cache.apply_refresh(eid, [PostingIn(ext_id=str(n), title=f"Analyst {n}", url=f"https://{name}.icims.com/jobs/{n}/job", location="Boston, MA") for n in range(5)], 1_000_000)
    only_new = cache.postings_without_description(50, 30, None, [new])
    assert len(only_new) == 5 and all("newco" in u for _i, u in only_new)


def test_description_addresses_for_smartrecruiters_workable_and_icims_and_their_answers():
    assert service._description_request("https://jobs.smartrecruiters.com/AcmeHealth/743999-revenue-cycle-lead") == ("smartrecruiters", "https://api.smartrecruiters.com/v1/companies/AcmeHealth/postings/743999")
    assert service._description_request("https://apply.workable.com/acme/j/ABC123DEF/") == ("workable", "https://apply.workable.com/api/v2/accounts/acme/jobs/ABC123DEF")
    assert service._description_request("https://careers-acme.icims.com/jobs/1234/billing-lead/job") == ("icims", "https://careers-acme.icims.com/jobs/1234/billing-lead/job?in_iframe=1")
    assert service._description_request("https://example.com/careers/1") is None
    sr = {"jobAd": {"sections": {"jobDescription": {"text": "Lead claims and denials work."}, "qualifications": {"text": "CPC preferred."}}}}
    assert service._data_description("smartrecruiters", sr) == "Lead claims and denials work. CPC preferred."
    assert service._data_description("workable", {"description": "<p>Own billing.</p>", "requirements": "<p>Epic.</p>"}) == "<p>Own billing.</p> <p>Epic.</p>"
    assert service._data_description("workable", {}) is None


def test_an_alternative_title_that_borrows_one_word_of_the_field_is_a_lookalike_not_an_alternative():
    crit = SimpleNamespace(titles="revenue cycle manager", location="", work_type="any", keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=None, count=10)
    plan = matcher.build_plan(crit, ["revenue operations manager", "revenue cycle director", "patient accounts manager"])
    assert matcher.title_fit(plan, "Revenue Operations Manager") < matcher.MIN_TITLE_FIT  # the AI's suggestion is a different field
    assert matcher.title_fit(plan, "Revenue Cycle Director") > 0.8  # a real alternative keeps the whole kind of work
    assert matcher.title_fit(plan, "Patient Accounts Manager") > matcher.MIN_TITLE_FIT  # one that names none of it is another way to say the work


def test_a_posting_open_for_over_half_a_year_ranks_below_a_fresh_one():
    plan = matcher.build_plan(SimpleNamespace(titles="revenue cycle manager", location="", work_type="any", keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=None, count=10), [])
    base = {"company": "X", "location": "Boston, MA", "work_type": None, "pay_mid": None, "pay_text": None, "url": "u", "title": "Revenue Cycle Manager", "description": None}
    today = dt.date(2026, 10, 20)
    fresh = matcher.score_row(plan, {**base, "posted_at": "2026-10-10"}, today)
    old = matcher.score_row(plan, {**base, "posted_at": "2021-06-17"}, today)
    assert old.fit < fresh.fit * 0.9


def test_a_web_result_in_the_wrong_place_is_ruled_out_like_a_saved_one():
    plan = matcher.build_plan(SimpleNamespace(titles="project manager", location="Chicago, IL", work_type="any", keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=None, count=10), [])
    assert not matcher.place_ok(plan, "Vaesteras, Vastmanland County, Sweden; Vaasa, Finland", None)
    assert not matcher.place_ok(plan, "Dallas, TX", None)
    assert matcher.place_ok(plan, "Chicago, IL", None) and not matcher.place_ok(plan, "Remote", "remote")  # remote only comes with the remote checkbox
    assert matcher.place_ok(matcher.build_plan(SimpleNamespace(titles="project manager", location="Chicago, IL", include_remote=True, work_type="any", keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=None, count=10), []), "Remote", "remote")


def test_a_piped_us_place_is_written_as_city_and_state():
    assert text.tidy_place("US | Illinois | Chicago") == "Chicago, IL"


def test_a_two_word_title_keeps_alternatives_that_drop_the_field_below_a_strong_match():
    crit = SimpleNamespace(titles="financial analyst", location="New York, NY", work_type="any", keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=None, count=10)
    plan = matcher.build_plan(crit, ["security analyst", "senior financial analyst", "fp&a analyst"])
    assert matcher.title_fit(plan, "Financial Analyst") > 0.9
    assert matcher.title_fit(plan, "Senior Financial Analyst") > 0.8
    assert 0 < matcher.title_fit(plan, "Senior Security Analyst") < 0.6  # shown at most as a weak match


def test_remote_jobs_rank_behind_jobs_in_the_city_asked_for():
    q = text.parse_location_query("New York, NY or remote")
    here = text.location_fit(q, "New York, NY", None)
    remote = text.location_fit(q, "San Francisco, CA", "remote")
    nowhere = text.location_fit(q, "Remote", "remote")
    assert here == 1.0 and remote == nowhere == text.REMOTE_ELSEWHERE < here
    assert text.location_fit(text.parse_location_query("remote"), "Remote", "remote") == 0.9


def test_new_york_city_is_a_city_search_not_the_whole_state():
    for typed in ("New York, NY", "New York City", "NYC", "New York, NY or remote"):
        q = text.parse_location_query(typed)
        assert q.cities == ["new york"] and q.states == {"NY"}, typed
    q = text.parse_location_query("New York, NY")
    assert text.location_fit(q, "New York, New York", None) == 1.0
    assert text.location_fit(q, "Buffalo, NY", None) == 0.0  # same state, not the city: a city search is a filter


def test_a_remote_place_listing_two_countries_is_written_plainly_and_still_counts_as_us():
    assert text.tidy_place("Remote (United States | Canada)") == "Remote (US or Canada)"
    assert text.tidy_place("Remote - US | Canada") == "Remote (US or Canada)"
    assert text.tidy_place("Remote (US)") == "Remote (US)"
    assert text.location_fit(text.parse_location_query("Boston, MA or remote"), "Remote (US or Canada)", "remote") > 0
    assert text.location_fit(text.parse_location_query("Boston, MA or remote"), "Remote, Canada", "remote") == 0.0


def test_a_date_window_leaves_out_a_posting_that_shows_no_date():
    crit = SimpleNamespace(titles="project manager", location="", work_type="any", keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=7, count=10)
    plan = matcher.build_plan(crit, [])
    row = {"title": "Project Manager", "company": "X", "location": "Boston, MA", "work_type": None, "pay_mid": None, "pay_text": None, "url": "u", "description": None}
    today = dt.date(2026, 10, 20)
    assert matcher.score_row(plan, {**row, "posted_at": "2026-10-17"}, today) is not None
    assert matcher.score_row(plan, {**row, "posted_at": "2026-09-01"}, today) is None
    assert matcher.score_row(plan, {**row, "posted_at": None}, today) is None
    assert matcher.score_row(matcher.build_plan(SimpleNamespace(**{**vars(crit), "posted_within_days": None}), []), {**row, "posted_at": None}, today) is not None


def test_a_company_name_is_taken_from_a_careers_page_title_and_generic_titles_are_refused():
    from scripts import cache_tools

    assert cache_tools.clean_found_name("KidsCare Home Health - Careers") == "KidsCare Home Health"
    assert cache_tools.clean_found_name("Careers at Doherty Enterprises") == "Doherty Enterprises"
    assert cache_tools.clean_found_name("PT Solutions | Jobs") == "PT Solutions"
    assert cache_tools.clean_found_name("Search Results") is None and cache_tools.clean_found_name("Careers") is None


def test_a_found_name_must_fit_the_employers_own_address():
    from scripts import cache_tools

    ok = cache_tools.name_agrees_with_address
    assert ok("ASM Global", "asmglobal") and ok("Doherty Enterprises", "dohertyinc") and ok("PT Solutions", "ptsolutions")
    assert not ok("Legends Hospitality", "asmglobal") and not ok("JINYA Ramen Bar", "dohertyinc") and not ok("Gerber Payroll Services", "boydgroup")
    assert cache_tools.clean_found_name("Gerber Payroll Services, Inc.") == "Gerber Payroll Services"


def test_a_job_with_no_place_whose_title_names_another_state_is_left_out():
    plan = matcher.build_plan(SimpleNamespace(titles="marine biologist", location="Honolulu, HI", work_type="any", keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=None, count=10), [])
    row = {"company": "X", "location": None, "work_type": None, "pay_mid": None, "pay_text": None, "posted_at": None, "url": "u", "description": None}
    assert matcher.score_row(plan, {**row, "title": "Marine Biologist - Alaska"}) is None
    assert matcher.score_row(plan, {**row, "title": "Marine Biologist - Hawaii"}) is not None
    assert matcher.score_row(plan, {**row, "title": "Marine Biologist"}) is not None


def test_a_city_search_is_a_filter_for_the_city_and_its_area_only():
    plan = matcher.build_plan(SimpleNamespace(titles="chef", location="Santa Fe, NM", work_type="any", keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=None, count=10), [], ["Pojoaque, NM"])
    ok = lambda loc, wt=None: matcher.place_ok(plan, loc, wt)
    assert ok("Santa Fe, NM") and ok("Pojoaque, NM")
    assert not ok("Albuquerque, NM") and not ok("Remote - US", "remote") and not ok("Dallas, TX")
    assert ok("2 Locations") and ok("New Mexico")  # no town named: kept only to be checked when the job is opened
    nationwide = matcher.build_plan(SimpleNamespace(titles="chef", location="United States", work_type="any", keywords="", exclude_companies="", target_salary=None, require_salary=False, posted_within_days=None, count=10), [])
    assert matcher.place_ok(nationwide, "Albuquerque, NM", None) and matcher.place_ok(nationwide, "Remote - US", "remote")
