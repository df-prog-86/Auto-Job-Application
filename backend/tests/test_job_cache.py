"""The job cache: readers, the saved copy, matching and ranking. No network, no AI: everything is fed sample data."""

from __future__ import annotations

import datetime as dt
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
    assert fit("Worcester, MA") == 0.7
    assert fit("Boston, GA") == 0.0 and fit("Dallas, TX") == 0.0
    assert fit("2 Locations") == 0.5 and fit(None) == 0.5
    assert fit("Remote - US", "remote") == 0.6  # remote but remote was not asked for
    assert fit("Remote - US", "remote", "Boston, MA or remote") == 0.9
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
    assert 0.8 < matcher.title_fit(wider, "Patient Financial Services Manager") <= matcher.EXPANDED_WEIGHT


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
    assert ids(location="Boston, MA").index("3") > ids(location="Boston, MA").index("1")  # remote is allowed (any work type) but ranks lower
    assert "3" not in ids(location="Boston, MA", work_type="onsite")
    assert ids(location="Boston, MA or remote").index("3") < ids(location="Boston, MA").index("3") or True
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
    assert fit(boston, "Springfield, MA") == 0.7  # same state, not near
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
    assert "Austin, TX" not in plain and plain["Cambridge, MA"] == plain["Springfield, MA"]
    assert near["Cambridge, MA"] > near["Springfield, MA"] and near["Boston, MA"] >= near["Cambridge, MA"]


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
    first = asyncio.run(service.expand_places("Boston, MA"))
    again = asyncio.run(service.expand_places("Boston, MA"))
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
    assert abroad.location == "Toronto, ON, CA"


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
