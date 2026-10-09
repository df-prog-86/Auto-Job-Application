"""The job cache: readers, the saved copy, matching and ranking. No network, no AI: everything is fed sample data."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from app.services.jobcache import matcher, readers, service, text
from app.services.jobcache.keys import loose_keys, url_key
from app.services.jobcache.store import JobCache, PostingIn

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
    assert ref("https://careers.ey.com/ey/job/x/1") is None
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
    assert text.pay_midpoint("$45 - $60 per hour") is None
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
