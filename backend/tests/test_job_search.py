"""Job Search: web search results, de-duplication, Add to jobs, Remove."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from app.services.llm.client import ChatCompletionResult

ITEMS = [
    {"title": "Revenue Cycle Analyst", "company": "Acme Health", "location": "Remote, US", "work_type": "remote",
     "salary": "$85,000 - $95,000", "posted": "2026-09-30", "url": "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/Remote/Analyst_R1?utm_source=x",
     "summary": "Analyze denials and payer trends."},
    {"title": "Revenue Cycle Billing Analyst", "company": "Beta Care", "location": "Boston, MA", "work_type": "hybrid", "salary": None, "posted": "2020-01-01",
     "url": "https://jobs.betacare.com/postings/42", "summary": "Own claim edits."},
    {"title": "Revenue Cycle Analyst No Link", "company": "Gamma", "location": None, "work_type": "unknown", "salary": None,
     "url": "not a url", "summary": "x"},
    {"title": "Revenue Cycle Analyst Saved", "company": "Delta", "location": None, "work_type": "remote", "salary": None,
     "url": "https://jobs.deltahealth.com/jobs/7", "summary": "x"},
]


@pytest.fixture()
def search(monkeypatch, app_and_db):
    from app.config import settings
    from app.services.discovery import web_search

    monkeypatch.setattr(settings, "PRIMARY_FAST_MODEL", "test/model")

    async def fake(self, **kwargs):
        assert kwargs["extra"]["plugins"][0]["id"] == "web"
        raw = {
            "choices": [
                {
                    "message": {
                        "content": "ignored",
                        "annotations": [
                            {"type": "url_citation",
                             "url_citation": {"url": "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/Remote/Analyst_R1"}}
                        ],
                    }
                }
            ]
        }
        return ChatCompletionResult(content="Here you go:\n```json\n" + json.dumps(ITEMS) + "\n```", input_tokens=1, output_tokens=1, raw=raw)

    async def unknown(url):
        return None  # tests never visit real sites

    async def no_dates(items, within_days, need_pay=False):
        return items, 0  # tests never visit real sites

    monkeypatch.setattr(web_search, "check_live", unknown)
    monkeypatch.setattr(web_search, "fill_posted_dates", no_dates)

    async def no_ats(items):
        return items, 0

    monkeypatch.setattr(web_search, "enrich_from_ats", no_ats)

    async def no_upgrade(items):
        return items

    monkeypatch.setattr(web_search, "upgrade_to_ats_links", no_upgrade)
    monkeypatch.setattr(web_search.LLMClient, "chat_completion", fake)
    return app_and_db


def _saved_job(SessionLocal) -> None:
    from app.models.jobs import Job

    now = dt.datetime.now(dt.timezone.utc)
    with SessionLocal() as db:
        db.add(Job(canonical_job_key="k-delta", company="Delta", normalized_company="delta", title="Analyst",
                   normalized_title="analyst", canonical_application_url="https://jobs.deltahealth.com/jobs/7",
                   first_seen=now, last_seen=now, application_status="not_started"))
        db.commit()


def test_search_needs_the_ai_connection(app_and_db):
    client, _ = app_and_db
    res = client.post("/api/v1/job-search/run", json={"titles": "revenue cycle analyst"})
    assert res.status_code == 503


def test_search_keeps_real_links_marks_grounded_ones_and_skips_known_ones(search):
    client, SessionLocal = search
    _saved_job(SessionLocal)
    out = client.post("/api/v1/job-search/run", json={"titles": "revenue cycle analyst", "work_type": "remote"}).json()
    assert out["found"] == 2 and out["skipped"] == 1  # the bad link is dropped, the saved job is skipped
    by_title = {r["title"]: r for r in out["results"]}
    assert set(by_title) == {"Revenue Cycle Analyst", "Revenue Cycle Billing Analyst"}
    assert by_title["Revenue Cycle Analyst"]["grounded"] is True  # the search engine returned this link
    assert "utm_source" not in by_title["Revenue Cycle Analyst"]["url"]
    assert by_title["Revenue Cycle Billing Analyst"]["grounded"] is False

    again = client.post("/api/v1/job-search/run", json={"titles": "revenue cycle analyst"}).json()
    assert len(again["results"]) == 2  # the same jobs come back, nothing is duplicated
    with SessionLocal() as db:
        from app.models.job_search import JobSearchResult

        assert db.query(JobSearchResult).count() == 2


def test_a_new_search_shows_only_its_own_jobs_and_sets_the_old_ones_aside(search):
    client, SessionLocal = search
    _saved_job(SessionLocal)
    first = client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()
    assert len(first["results"]) == 2
    from app.models.job_search import JobSearchResult

    with SessionLocal() as db:
        db.add(JobSearchResult(title="Old leftover", company="Acme", url="https://acme.example.com/jobs/1",
                               url_key="acme.example.com/jobs/1", status="new", criteria={}))
        db.commit()
    out = client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()
    assert "Old leftover" not in [r["title"] for r in out["results"]]
    with SessionLocal() as db:
        assert db.query(JobSearchResult).filter(JobSearchResult.title == "Old leftover").one().status == "stale"


def test_add_uses_the_summary_when_the_page_cannot_be_read_and_remove_hides_a_result(search, monkeypatch):
    from app.services.discovery import manual_extraction

    client, SessionLocal = search
    _saved_job(SessionLocal)  # the mocked search also returns a posting that is already saved

    async def blocked(url):
        raise manual_extraction.ManualExtractionError("blocked")

    monkeypatch.setattr(manual_extraction, "fetch_page", blocked)
    out = client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()
    first = next(r for r in out["results"] if r["title"] == "Revenue Cycle Billing Analyst")
    other = next(r for r in out["results"] if r["title"] == "Revenue Cycle Analyst")

    added = client.post(f"/api/v1/job-search/results/{first['id']}/add").json()
    assert added["from_summary"] is True and added["job"]["title"] == "Revenue Cycle Billing Analyst"
    assert "Revenue Cycle Billing Analyst" in [j["title"] for j in client.get("/api/v1/jobs").json()]

    assert client.post(f"/api/v1/job-search/results/{other['id']}/remove").json()["status"] == "removed"
    assert client.get("/api/v1/job-search/results").json()["results"] == []
    assert client.post(f"/api/v1/job-search/results/{other['id']}/add").status_code == 404  # gone from the list

    # A removed posting is not offered again by a later search.
    assert client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()["found"] == 0


def test_clear_removes_everything_waiting(search):
    client, SessionLocal = search
    _saved_job(SessionLocal)
    client.post("/api/v1/job-search/run", json={"titles": "analyst"})
    assert client.post("/api/v1/job-search/clear").json() == {"cleared": 2}
    assert client.get("/api/v1/job-search/results").json()["results"] == []


def test_excluded_companies_and_required_pay_are_left_out(search):
    client, SessionLocal = search
    out = client.post(
        "/api/v1/job-search/run",
        json={"titles": "analyst", "exclude_companies": "beta care, delta", "require_salary": True},
    ).json()
    assert [r["title"] for r in out["results"]] == ["Revenue Cycle Analyst"]  # Beta excluded, others have no pay


def test_a_job_added_elsewhere_disappears_from_the_search_list(search):
    client, SessionLocal = search
    client.post("/api/v1/job-search/run", json={"titles": "analyst"})
    _saved_job(SessionLocal)  # the Delta posting now sits on the Jobs page
    titles = [r["title"] for r in client.get("/api/v1/job-search/results").json()["results"]]
    assert "Revenue Cycle Analyst Saved" not in titles and "Revenue Cycle Billing Analyst" in titles


def test_clearly_closed_postings_are_dropped_but_unclear_ones_stay(search, monkeypatch):
    from app.services.discovery import web_search

    client, _ = search

    async def verdict(url):
        return False if "acme" in url else None  # Acme is closed; the rest could not be checked

    monkeypatch.setattr(web_search, "check_live", verdict)
    out = client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()
    assert "Revenue Cycle Analyst" not in [r["title"] for r in out["results"]]
    assert "Revenue Cycle Billing Analyst" in [r["title"] for r in out["results"]]
    assert out["skipped"] >= 1


def test_closed_page_detection():
    from app.services.discovery.web_search import is_public_host, looks_closed

    u = "https://careers.example.com/jobs/123-director"
    assert not looks_closed(u, u, 200, "Director. Apply now.")
    assert looks_closed(u, u, 200, "Sorry, this job is no longer accepting applications.")
    assert looks_closed(u, u, 404, "")
    assert not looks_closed(u, u, 403, "")  # blocked is not the same as closed
    assert looks_closed(u, "https://careers.example.com/", 200, "Welcome")  # bounced to the front page
    assert not is_public_host("http://localhost:8765/x") and not is_public_host("http://10.0.0.5/")
    assert is_public_host("https://careers.example.com/j")


def test_salary_minimum_is_a_floor_on_the_pay_midpoint_with_five_percent_slack(search):
    from app.services.discovery.web_search import salary_floor, salary_midpoint

    assert salary_floor(100000) == 95000
    assert salary_midpoint("$80,000 - $100,000") == 90000
    assert salary_midpoint("$85k") == 85000
    assert salary_midpoint("$45 - $60 per hour") == 52.5 * 2080 and salary_midpoint("Competitive") is None

    client, _ = search
    low = client.post("/api/v1/job-search/run", json={"titles": "analyst", "target_salary": 100000}).json()
    titles = [r["title"] for r in low["results"]]
    assert "Revenue Cycle Analyst" not in titles  # posted $85,000 is under the $95,000 floor
    assert "Revenue Cycle Billing Analyst" in titles  # no posted pay stays unless the pay box is ticked


def test_posted_date_and_pay_range_follow_the_job_into_the_jobs_list(search, monkeypatch):
    from app.services.discovery import manual_extraction

    client, _ = search

    async def blocked(url):
        raise manual_extraction.ManualExtractionError("blocked")

    monkeypatch.setattr(manual_extraction, "fetch_page", blocked)
    out = client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()
    acme = next(r for r in out["results"] if r["title"] == "Revenue Cycle Analyst")
    assert acme["posted_at"] == "2026-09-30" and acme["salary_text"] == "$85,000 - $95,000"

    job = client.post(f"/api/v1/job-search/results/{acme['id']}/add").json()["job"]
    assert job["posted_at"] == "2026-09-30"
    assert job["salary"]["text"] == "$85,000 - $95,000"
    assert job["salary"]["min"] == 85000 and job["salary"]["max"] == 95000


def test_postings_older_than_the_window_are_left_out(search):
    client, _ = search
    out = client.post("/api/v1/job-search/run", json={"titles": "analyst", "posted_within_days": 7}).json()
    assert "Revenue Cycle Billing Analyst" not in [r["title"] for r in out["results"]]  # posted in 2020


_PROFILE = {
    "extraction": {
        "contact": {"name": "Jane Doe", "email": "jane@example.com"},
        "employment": [
            {"employer": "Acme Corp", "title": "Revenue Cycle Billing Analyst", "start_date": "2021-04", "end_date": None,
             "source_text": "Worked denials and payer follow up."}
        ],
        "education": [],
        "skills": ["SQL"],
        "certifications": [],
        "projects": [],
    },
    "approved_claims": [],
    "resume_filename": "resume.docx",
}


def _profile(client):
    return client.post("/api/v1/profile/commit", json=_PROFILE).json()


class _FakeMatchRouter:
    def __init__(self, db):
        pass

    async def get_structured(self, **kwargs):
        from app.services.llm.schemas import ResumeJobMatchResult

        assert "Denial work" in kwargs["messages"][1]["content"]  # the posting's requirements were provided
        return ResumeJobMatchResult(match_percentage=81, summary="Strong billing background.", gaps=["Epic Resolute"])


def test_match_score_is_asked_for_after_the_requirements_are_read_and_travels_with_the_job(search, monkeypatch):
    from app.services.discovery import manual_extraction
    from app.services.discovery.base import RawJobPosting

    client, _ = search
    _profile(client)

    async def page(url):
        return manual_extraction.FetchedPage(url=url, json_ld_blocks=[], body_text="x", title="x")

    async def extract(db, **kwargs):
        return RawJobPosting(external_job_id=None, title="Revenue Cycle Analyst", company="Acme Health", location=None,
                             description_html="<p>Denial work and payer trends. 3+ years. " + ("Own claim edits and appeal letters for the billing team. " * 8) + "</p>", application_url=kwargs["url"])

    monkeypatch.setattr(manual_extraction, "fetch_page", page)
    monkeypatch.setattr(manual_extraction, "extract_job_posting", extract)
    monkeypatch.setattr("app.services.qualification.pipeline.ModelRouter", _FakeMatchRouter)

    out = client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()
    acme = next(r for r in out["results"] if r["title"] == "Revenue Cycle Analyst")
    assert acme["match_score"] is None  # never scored on its own

    scored = client.post(f"/api/v1/job-search/results/{acme['id']}/score").json()
    assert scored["match_score"] == 0.81 and scored["match_from_page"] is True
    assert scored["match_gaps"] == ["Epic Resolute"]

    job = client.post(f"/api/v1/job-search/results/{acme['id']}/add").json()["job"]
    assert job["evaluation"]["overall_score"] == 0.81  # no second scoring needed on the Jobs page


def test_match_score_needs_a_profile_and_is_refused_when_only_the_summary_is_available(search, monkeypatch):
    from app.services.discovery import manual_extraction

    client, _ = search
    out = client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()
    first = out["results"][0]
    assert client.post(f"/api/v1/job-search/results/{first['id']}/score").status_code == 409  # no resume yet

    _profile(client)

    async def blocked(url):
        raise manual_extraction.ManualExtractionError("blocked")

    class _Router(_FakeMatchRouter):
        async def get_structured(self, **kwargs):
            raise AssertionError("must not score from a one-line summary")

    monkeypatch.setattr(manual_extraction, "fetch_page", blocked)
    monkeypatch.setattr("app.services.qualification.pipeline.ModelRouter", _Router)
    refused = client.post(f"/api/v1/job-search/results/{first['id']}/score")
    assert refused.status_code == 422 and "couldn't be read" in refused.json()["detail"]
    assert client.get("/api/v1/job-search/results").json()["results"][0]["match_score"] is None


def test_match_score_says_when_the_posting_is_closed(search, monkeypatch):
    import httpx

    from app.services.discovery import manual_extraction

    client, _ = search
    _profile(client)
    first = client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()["results"][0]

    async def gone(url):
        request = httpx.Request("GET", url)
        error = httpx.HTTPStatusError("gone", request=request, response=httpx.Response(404, request=request))
        raise manual_extraction.ManualExtractionError("gone") from error

    monkeypatch.setattr(manual_extraction, "fetch_page", gone)
    refused = client.post(f"/api/v1/job-search/results/{first['id']}/score")
    assert refused.status_code == 410 and "closed" in refused.json()["detail"]


# ---- original source lookup for results found on job boards ----

def test_job_boards_are_recognised_but_employer_sites_are_not():
    from app.services.discovery.web_search import is_aggregator

    assert is_aggregator("https://www.linkedin.com/jobs/view/123")
    assert is_aggregator("https://uk.indeed.com/viewjob?jk=1")
    assert is_aggregator("https://chicago.builtin.com/job/x")
    assert not is_aggregator("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/1")
    assert not is_aggregator("https://boards.greenhouse.io/acme/jobs/1")
    assert not is_aggregator("https://notlinkedin.example.com/jobs/1")


def _board_items():
    base = {"company": "Acme Health", "location": None, "work_type": "remote", "salary": None, "summary": "x"}
    return [
        {**base, "title": "Revenue Cycle Analyst", "url": "https://www.linkedin.com/jobs/view/1", "url_key": "linkedin.com/jobs/view/1"},
        {**base, "title": "Revenue Cycle Billing Analyst", "url": "https://www.indeed.com/viewjob?jk=2", "url_key": "indeed.com/viewjob?jk=2"},
        {**base, "title": "Claims Analyst", "url": "https://jobs.acme.com/claims", "url_key": "jobs.acme.com/claims"},
    ]


def _resolver(monkeypatch, answers, accept=True):
    from app.config import settings
    from app.services.discovery import web_search

    monkeypatch.setattr(settings, "PRIMARY_FAST_MODEL", "test/model")

    async def fake(self, **kwargs):
        prompt = json.dumps(kwargs["messages"])
        for title, url in answers.items():
            if title in prompt:
                return ChatCompletionResult(content=json.dumps({"url": url}), input_tokens=1, output_tokens=1, raw={})
        return ChatCompletionResult(content="null", input_tokens=1, output_tokens=1, raw={})

    async def acceptable(item, url, grounded):
        return accept

    monkeypatch.setattr(web_search.LLMClient, "chat_completion", fake)
    monkeypatch.setattr(web_search, "_original_is_acceptable", acceptable)
    return web_search


def test_board_result_is_swapped_for_the_employers_own_posting(monkeypatch):
    import asyncio

    ws = _resolver(monkeypatch, {"Revenue Cycle Analyst": "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/R1?utm_source=x"})
    out, dropped = asyncio.run(ws.resolve_original_sources(_board_items()))
    by_title = {i["title"]: i for i in out}
    assert by_title["Revenue Cycle Analyst"]["url"] == "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/R1"
    assert "Revenue Cycle Billing Analyst" not in by_title  # no original found, so the board link is dropped
    assert by_title["Claims Analyst"]["url"] == "https://jobs.acme.com/claims"  # employer links are untouched
    assert dropped == 1


def test_board_result_is_dropped_when_the_found_link_does_not_check_out(monkeypatch):
    import asyncio

    ws = _resolver(monkeypatch, {"Revenue Cycle Analyst": "https://acme.example.com/jobs/1"}, accept=False)
    out, dropped = asyncio.run(ws.resolve_original_sources(_board_items()))
    assert [i["title"] for i in out] == ["Claims Analyst"] and dropped == 2


def test_two_board_results_pointing_at_one_original_are_merged(monkeypatch):
    import asyncio

    same = "https://acme.example.com/jobs/1"
    ws = _resolver(monkeypatch, {"Revenue Cycle Analyst": same, "Revenue Cycle Billing Analyst": same})
    out, dropped = asyncio.run(ws.resolve_original_sources(_board_items()))
    assert sorted(i["title"] for i in out) == ["Claims Analyst", "Revenue Cycle Analyst"] and dropped == 1


def test_only_the_first_few_board_results_are_looked_up(monkeypatch):
    import asyncio

    ws = _resolver(monkeypatch, {})
    base = _board_items()[0]
    many = [{**base, "title": f"Role {n}", "url": f"https://www.linkedin.com/jobs/view/{n}", "url_key": f"linkedin.com/jobs/view/{n}"}
            for n in range(ws.MAX_RESOLVE + 4)]
    out, dropped = asyncio.run(ws.resolve_original_sources(many))
    assert out == [] and dropped == len(many)


def test_a_board_page_is_never_accepted_as_the_original(monkeypatch):
    import asyncio
    from app.services.discovery import web_search as ws

    ok = asyncio.run(ws._original_is_acceptable(_board_items()[0], "https://www.indeed.com/viewjob?jk=9", True))
    assert ok is False


def test_posted_date_is_read_from_the_posting_page():
    import datetime as dt
    from app.services.discovery.web_search import extract_posted_date

    assert extract_posted_date('<script type="application/ld+json">{"datePosted": "2026-09-30T00:00:00"}</script>') == dt.date(2026, 9, 30)
    assert extract_posted_date('<meta property="article:published_time" content="2026-09-12T10:00:00Z">') == dt.date(2026, 9, 12)
    assert extract_posted_date("<p>Posted yesterday</p>") == dt.date.today() - dt.timedelta(days=1)
    assert extract_posted_date("<p>Posted 2 weeks ago</p>") == dt.date.today() - dt.timedelta(days=14)
    assert extract_posted_date("<p>No date here</p>") is None


def test_date_window_drops_old_and_undated_postings_but_no_window_keeps_undated(monkeypatch):
    import asyncio
    import datetime as dt
    from app.services.discovery import web_search as ws

    async def no_visit(*a, **k):
        raise RuntimeError("tests never visit real sites")

    monkeypatch.setattr(ws, "safe_get", no_visit)
    today = dt.date.today()
    mk = lambda n, d: {"title": n, "url": f"https://jobs.example.com/{n}", "posted_at": d}
    items = [mk("new", today - dt.timedelta(days=3)), mk("old", today - dt.timedelta(days=40)), mk("undated", None)]
    kept, dropped = asyncio.run(ws.fill_posted_dates(items, 14))
    assert [i["title"] for i in kept] == ["new"] and dropped == 2
    kept_all, none_dropped = asyncio.run(ws.fill_posted_dates(items, 0))
    assert len(kept_all) == 3 and none_dropped == 0  # no window asked: nothing is dropped for its date


def test_workday_postings_are_read_from_workdays_own_data():
    import datetime as dt
    from app.services.discovery.ats import workday_api_url, workday_info

    url = "https://huron.wd1.myworkdayjobs.com/en-US/huroncareers/job/Healthcare-Consulting-Manager---Revenue-Cycle_JR-0016103"
    assert workday_api_url(url) == "https://huron.wd1.myworkdayjobs.com/wday/cxs/huron/huroncareers/job/Healthcare-Consulting-Manager---Revenue-Cycle_JR-0016103"
    assert workday_api_url("https://acme.wd5.myworkdayjobs.com/careers/job/Remote/Analyst_R1") == \
        "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/careers/job/Remote/Analyst_R1"
    assert workday_api_url("https://jobs.example.com/job/1") is None
    assert workday_info(200, {"jobPostingInfo": {"startDate": "2026-08-20"}}).posted == dt.date(2026, 8, 20)
    assert workday_info(200, {"jobPostingInfo": {"postedOn": "Posted 30+ Days Ago"}}).posted == dt.date.today() - dt.timedelta(days=30)
    assert workday_info(200, {}).posted is None


# ---- one search per kind of source, checked by the employers' own systems ----

def test_each_source_gets_its_own_domain_filter(search):
    from app.services.discovery import web_search

    client, _ = search
    seen = []
    original = web_search.LLMClient.chat_completion

    async def spy(self, **kwargs):
        seen.append(kwargs["extra"]["plugins"][0])
        return await original(self, **kwargs)

    web_search.LLMClient.chat_completion = spy
    try:
        client.post("/api/v1/job-search/run", json={"titles": "revenue cycle consultant"})
    finally:
        web_search.LLMClient.chat_completion = original
    assert len(seen) == 2  # one for the hiring systems, one for company sites
    ats = [p for p in seen if "include_domains" in p][0]
    assert "*.myworkdayjobs.com" in ats["include_domains"] and "jobs.ashbyhq.com" in ats["include_domains"]
    web = [p for p in seen if "exclude_domains" in p][0]
    assert "linkedin.com" in web["exclude_domains"] and all(p["engine"] == "exa" and "mode" not in p for p in seen)


def test_search_still_returns_results_when_one_source_fails(search, monkeypatch):
    from app.services.discovery import web_search

    client, _ = search
    calls = {"n": 0}
    original = web_search.LLMClient.chat_completion

    async def flaky(self, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("source down")
        return await original(self, **kwargs)

    monkeypatch.setattr(web_search.LLMClient, "chat_completion", flaky)
    res = client.post("/api/v1/job-search/run", json={"titles": "analyst"})
    assert res.status_code == 200 and res.json()["found"] >= 1


def test_ats_answers_are_read_correctly():
    import datetime as dt
    from app.services.discovery import ats

    assert ats.greenhouse_ref("https://job-boards.greenhouse.io/kodiaksolutions/jobs/4095330009") == ("kodiaksolutions", "4095330009")
    assert ats.greenhouse_ref("https://example.com/x/jobs/1") is None
    assert ats.greenhouse_info(404, None).live is False
    assert ats.greenhouse_info(200, {"first_published": "2026-09-01T10:00:00-04:00"}).posted == dt.date(2026, 9, 1)
    uid = "c771bcbd-1cc6-4228-a50a-8f18b8da2c0b"
    assert ats.ashby_ref(f"https://jobs.ashbyhq.com/magical/{uid}") == ("magical", uid)
    board = {"jobs": [{"id": uid, "isListed": True, "publishedAt": "2026-09-10T00:00:00.000+00:00"}]}
    assert ats.ashby_info(200, board, uid).posted == dt.date(2026, 9, 10)
    assert ats.ashby_info(200, board, "other-id-0000-0000-0000").live is False  # not on the board any more
    assert ats.ashby_info(500, None, uid).live is None  # unknown never removes
    assert ats.lever_ref(f"https://jobs.lever.co/acme/{uid}") == ("acme", uid)
    assert ats.lever_info(200, {"createdAt": 1788000000000}).live is True
    assert ats.workday_info(404, None).live is False
    assert ats.workday_info(200, {"jobPostingInfo": {"canApply": False}}).live is False


def test_closed_postings_reported_by_their_own_system_are_removed(monkeypatch):
    import asyncio
    from app.services.discovery import ats, web_search as ws

    async def fake(url, client, boards):
        return ats.AtsInfo(live=False, checked=True) if "closed" in url else ats.AtsInfo(live=True, checked=True)

    monkeypatch.setattr(ws.ats, "inspect", fake)
    items = [{"title": "a", "url": "https://x.example.com/closed"}, {"title": "b", "url": "https://x.example.com/open"}]
    kept, gone = asyncio.run(ws.enrich_from_ats(items))
    assert [i["title"] for i in kept] == ["b"] and gone == 1 and kept[0]["ats_checked"] is True


def test_same_job_from_two_sources_is_one_result_and_the_ats_link_wins():
    from app.services.discovery.web_search import merge_same_jobs

    wd = "https://huron.wd1.myworkdayjobs.com/en-US/c/job/Boston/Revenue-Cycle-Consultant_R10234"
    site = {"title": "Revenue Cycle Consultant", "company": "Huron", "url": "https://huron.com/careers/1?jid=R10234", "grounded": True}
    ats = {"title": "Revenue Cycle  Consultant", "company": "HURON", "url": wd, "grounded": False}
    other = {"title": "Revenue Cycle Billing Analyst", "company": "Huron", "url": "https://huron.com/careers/2", "grounded": False}
    assert merge_same_jobs([site, ats, other]) == [ats, other]  # same requisition number: one job


def test_same_company_and_title_is_not_enough_to_merge_two_results():
    from app.services.discovery.web_search import merge_same_jobs

    boston = {"title": "Billing Analyst", "company": "Acme", "url": "https://boards.greenhouse.io/acme/jobs/111", "grounded": True}
    chicago = {"title": "Billing Analyst", "company": "Acme", "url": "https://boards.greenhouse.io/acme/jobs/222", "grounded": True}
    assert merge_same_jobs([boston, chicago]) == [boston, chicago]      # two job numbers on one board: two jobs
    site = {"title": "Billing Analyst", "company": "Acme", "url": "https://acme.com/careers/billing", "grounded": True}
    assert merge_same_jobs([boston, site]) == [boston, site]            # no shared number, link or text: kept apart
    text_a = "Lead the billing team and own charge capture and denials across the revenue cycle for our hospitals. " * 3
    a = {**boston, "_desc": text_a}
    b = {**site, "_desc": text_a + " Apply today."}
    assert merge_same_jobs([a, b]) == [a]                              # near-identical descriptions: one job (the ATS link wins)


def test_results_are_trimmed_to_the_count_with_verified_ones_first():
    from app.services.discovery.web_search import trim_to_count

    mk = lambda n, checked: {"title": n, "url": f"https://x.example.com/{n}", "ats_checked": checked}
    items = [mk("a", False), mk("b", True), mk("c", False), mk("d", True)]
    assert [i["title"] for i in trim_to_count(items, 2)] == ["b", "d"]
    assert [i["title"] for i in trim_to_count(items, 10)] == ["a", "b", "c", "d"]  # order kept, nothing lost


def test_search_results_carry_only_saved_fields_even_when_the_ats_check_ran(search, monkeypatch):
    from app.services.discovery import web_search

    client, _ = search

    async def marks(items):
        for i in items:
            i["ats_checked"], i["ats_live"] = True, True
        return items, 0

    monkeypatch.setattr(web_search, "enrich_from_ats", marks)
    res = client.post("/api/v1/job-search/run", json={"titles": "analyst"})
    assert res.status_code == 200 and res.json()["found"] >= 1


def test_unknown_job_sites_are_caught_by_how_they_look_but_employer_sites_are_not():
    from app.services.discovery.web_search import is_board_url

    assert is_board_url("https://jobs.digitalhire.com/job-listing/opening/3wLCvdw7", "Acme")
    assert is_board_url("https://diversityjobs.com/career/18417213/Consultant", "Huron")
    assert is_board_url("https://www.somenewjobsite.com/view/1", "Huron")  # not listed, but not the employer's either
    assert is_board_url("https://www.randomcompany.com/view/1", "Huron")  # any site that does not carry the employer's name
    assert not is_board_url("https://jobs.huron.com/x", "Huron Consulting Group")
    assert not is_board_url("https://careers.alvarezandmarsal.com/x", "Alvarez & Marsal")
    assert not is_board_url("https://fticonsulting.com/careers/1", "FTI Consulting")
    assert not is_board_url("https://careers-acme.icims.com/jobs/1", "Acme")
    assert not is_board_url("https://acme.wd5.myworkdayjobs.com/en-US/c/job/R1", "Acme")


def test_investor_and_community_job_boards_are_caught_by_their_address_pattern():
    from app.services.discovery.web_search import is_board_url

    assert is_board_url("https://jobs.rre.com/companies/ostro/jobs/96108253-director-senior-director-ostro-strategy", "Ostro")
    assert is_board_url("https://jobs.example-capital.com/companies/acme/jobs/123-analyst", "Acme")
    assert not is_board_url("https://acme.wd5.myworkdayjobs.com/en-US/c/job/R1", "Acme")
    assert not is_board_url("https://careers.acme.com/jobs/123-analyst", "Acme")


def test_pay_is_read_from_the_postings_own_data():
    from app.services import discovery  # noqa: F401
    from app.services.discovery import ats

    assert ats.extract_pay_text("<p>Base pay: $120,000 - $150,000 per year</p>") == "$120,000 - $150,000"
    assert ats.extract_pay_text("Salary $95K to $110K plus bonus") == "$95K to $110K"
    assert ats.extract_pay_text("&lt;p&gt;$80,000&nbsp;-&nbsp;$100,000&lt;/p&gt;") is not None  # escaped markup (Greenhouse)
    assert ats.extract_pay_text("Competitive pay and great benefits") is None
    assert ats.greenhouse_info(200, {"pay_input_ranges": [{"min_cents": 12000000, "max_cents": 15000000}]}).pay == "$120,000 - $150,000"
    assert ats.workday_info(200, {"jobPostingInfo": {"jobDescription": "<b>$100,000 - $130,000</b>"}}).pay == "$100,000 - $130,000"
    uid = "c771bcbd-1cc6-4228-a50a-8f18b8da2c0b"
    board = {"jobs": [{"id": uid, "compensation": {"compensationTierSummary": "$130K - $160K"}}]}
    assert ats.ashby_info(200, board, uid).pay == "$130K - $160K"
    assert ats.lever_info(200, {"salaryRange": {"min": 90000, "max": 110000}}).pay == "$90,000 - $110,000"


def test_only_show_jobs_with_pay_keeps_postings_whose_own_data_states_pay():
    from app.schemas.job_search import JobSearchIn
    from app.services.discovery.web_search import apply_pay_rules

    items = [{"title": "a", "salary_text": "$120,000 - $150,000"}, {"title": "b", "salary_text": None}, {"title": "c", "salary_text": "$40,000 - $50,000"}]
    kept, dropped = apply_pay_rules(items, JobSearchIn(titles="analyst", require_salary=True))
    assert [i["title"] for i in kept] == ["a", "c"] and dropped == 1
    kept, _ = apply_pay_rules(items, JobSearchIn(titles="analyst", target_salary=100000))
    assert [i["title"] for i in kept] == ["a", "b"]  # unknown pay stays; clearly low pay goes


def test_a_careers_site_that_runs_on_workday_is_swapped_for_its_workday_posting():
    from app.services.discovery.web_search import find_ats_link

    page = (
        '<a href="/about">About</a> <a href="https://bilh.wd1.myworkdayjobs.com/External/job/Beth-Israel/'
        'Process-Improvement-Project-Manager_JR103548/apply?utm_source=careersite&amp;utm_campaign=JR103548">Apply now</a>'
    )
    assert find_ats_link(page, "https://jobs.bilh.org/jobs/x/") == (
        "https://bilh.wd1.myworkdayjobs.com/External/job/Beth-Israel/Process-Improvement-Project-Manager_JR103548"
    )
    assert find_ats_link('<a href="https://job-boards.greenhouse.io/acme/jobs/123?gh_src=x">Apply</a>', "https://acme.com/c") == \
        "https://job-boards.greenhouse.io/acme/jobs/123"
    assert find_ats_link('<a href="/apply">Apply</a> <a href="https://www.linkedin.com/x">LinkedIn</a>', "https://acme.com/c") is None


def test_upgrade_swaps_the_link_and_merges_duplicates(monkeypatch):
    import asyncio
    from app.services.discovery import web_search as ws

    class Resp:
        status_code = 200
        url = "https://jobs.bilh.org/jobs/x/"
        text = '<a href="https://bilh.wd1.myworkdayjobs.com/External/job/A/Role_JR1/apply">Apply</a>'

    async def fake_get(*a, **k):
        return Resp()

    monkeypatch.setattr(ws, "safe_get", fake_get)
    items = [
        {"title": "a", "url": "https://jobs.bilh.org/jobs/x/", "url_key": "jobs.bilh.org/jobs/x"},
        {"title": "a", "url": "https://bilh.wd1.myworkdayjobs.com/External/job/A/Role_JR1", "url_key": "bilh.wd1.myworkdayjobs.com/external/job/a/role_jr1"},
    ]
    out = asyncio.run(ws.upgrade_to_ats_links(items))
    assert len(out) == 1 and out[0]["url"].startswith("https://bilh.wd1.myworkdayjobs.com/")


def test_the_apply_link_wins_and_a_page_already_on_a_hiring_system_is_left_alone():
    from app.services.discovery import ats

    page = (
        '<a href="https://acme.wd5.myworkdayjobs.com/en-US/c/job/Other-Role_R9">Similar job</a>'
        '<a href="https://acme.wd5.myworkdayjobs.com/en-US/c/job/This-Role_R1/apply?x=1">Apply</a>'
    )
    assert ats.find_ats_link(page, "https://careers.acme.com/jobs/1") == "https://acme.wd5.myworkdayjobs.com/en-US/c/job/This-Role_R1"
    assert ats.find_ats_link(page, "https://acme.wd5.myworkdayjobs.com/en-US/c/job/This-Role_R1") is None
    links = ["https://www.linkedin.com/x", "https://job-boards.greenhouse.io/acme/jobs/5", "https://job-boards.greenhouse.io/acme/jobs/6/apply"]
    assert ats.pick_ats_link(links, "https://acme.com/careers/6") == "https://job-boards.greenhouse.io/acme/jobs/6"
    assert ats.pick_ats_link(links, "https://job-boards.greenhouse.io/acme/jobs/6") is None
    assert ats.pick_ats_link(["https://www.linkedin.com/x"], "https://acme.com/c") is None


def test_lever_application_link_reads_the_posting_page_and_title():
    from app.services.discovery.manual_extraction import extract_from_lever_page, posting_url_for

    post = "https://jobs.lever.co/Acme/71580e53-408b-4084-9ba6-693c69564b39"
    assert posting_url_for(post + "/apply?lever-source=x") == post
    assert posting_url_for("https://example.com/jobs/1/apply") == "https://example.com/jobs/1/apply"
    got = extract_from_lever_page(post, "Acme Health - Revenue Cycle Manager", "About the role ...")
    assert (got.company, got.title, got.application_url) == ("Acme Health", "Revenue Cycle Manager", post)
    assert extract_from_lever_page("https://example.com/x", "Acme - Role", "") is None


def test_names_and_titles_are_tidied_twins_merged_and_off_topic_results_left_out():
    import datetime as dt

    from app.services.discovery import web_search
    from app.services.jobcache import matcher
    from app.services.jobcache.text import clean_company, clean_title

    assert clean_company("1000 Abbott Laboratories Inc(ALI)") == "Abbott Laboratories Inc"
    assert clean_company("LE001 Berkeley Research Group, LLC") == "Berkeley Research Group, LLC"
    assert clean_company("4100 Exact Sciences Corp") == "Exact Sciences Corp"
    assert clean_company("Danafarber") == "Dana-Farber Cancer Institute"
    assert clean_company("Massgeneralbrigham") == "Mass General Brigham"
    assert clean_company("Hcsc") == "HCSC"
    assert clean_company("Disney") == "Disney"
    assert clean_title("Program Manager at Massgeneralbrigham", "Massgeneralbrigham") == "Program Manager"
    assert clean_title("Senior Project Manager, Information Technology at Bilh", "Bilh") == "Senior Project Manager, Information Technology"
    assert clean_title("Analyst at Large Scale Data", "Acme") == "Analyst at Large Scale Data"  # not that employer: left alone

    day = dt.date(2026, 10, 7)
    twins = [
        {"title": "Marketing Project Manager", "company": "Abbott", "location": "Alameda", "salary_text": "$90,000 - $180,000", "posted_at": day, "url": "https://a.example/1?req=777"},
        {"title": "Marketing Project Manager", "company": "Exact Sciences", "location": "Alameda", "salary_text": "$90,000 - $180,000", "posted_at": day, "url": "https://b.example/2?req=777"},
        {"title": "Project Manager", "company": "Disney", "location": "Anaheim", "salary_text": None, "posted_at": day, "url": "https://c.example/3"},
        {"title": "Project Manager", "company": "Other", "location": "Anaheim", "salary_text": None, "posted_at": day, "url": "https://d.example/4"},
    ]
    kept = web_search.merge_twin_postings(twins)
    assert [i["company"] for i in kept] == ["Abbott", "Disney", "Other"]  # a posting with no stated pay is never joined to another

    class Criteria:
        titles = "project manager"
        location = "Boston, MA"
        work_type = "any"
        keywords = None
        target_salary = None
        exclude_companies = None
        posted_within_days = 0

    plan = matcher.build_plan(Criteria())
    assert matcher.title_fit(plan, "Sr. Enterprise Account Executive") < matcher.MIN_TITLE_FIT
    assert matcher.title_fit(plan, "Senior Project Manager") >= matcher.MIN_TITLE_FIT
    note = web_search.fit_note(plan, {"title": "Senior Project Manager", "location": "Boston, MA", "work_type": None, "posted_at": dt.date.today()})
    assert note == "Title matches closely · In your area · Posted today"


def test_results_carry_a_fit_score_and_a_short_reason(search):
    client, _ = search
    out = client.post("/api/v1/job-search/run", json={"titles": "revenue cycle analyst", "work_type": "remote"}).json()
    first = out["results"][0]
    assert first["fit_score"] is not None and 0 < first["fit_score"] <= 1
    assert "Title" in first["fit_note"]


def test_city_suggestions_complete_what_is_typed(search):
    from app.services.jobcache import places

    labels = lambda q, **kw: [p["label"] for p in places.suggest(q, **kw)]
    assert labels("Bost")[0] == "Boston, MA"
    assert labels("Orlan")[0] == "Orlando, FL"
    assert labels("bos, ma")[0] == "Boston, MA"
    assert "Boston, MA" not in labels("Bost, TX")
    assert labels("San ")[0] == "San Antonio, TX"  # larger cities first
    assert labels("B") == []  # too short to guess
    assert labels("Hartfo")[0] == "Hartford, CT"
    assert labels("Rem")[-1] == "Remote"
    assert labels("Zzyzx", extra_locations=["Zzyzxville, CA", "Zzyzxville, CA"]) == ["Zzyzxville, CA"]  # a town only the job lists mention

    client, _ = search
    got = client.get("/api/v1/job-search/places", params={"q": "Orlan"}).json()
    assert got[0] == {"label": "Orlando, FL", "city": "Orlando", "state": "FL"}


def test_title_and_keyword_suggestions():
    from app.services.jobcache import suggest

    rows = [("Project Manager", 40), ("Project Manager III", 5), ("Project Management Specialist", 12), ("Senior Project Manager", 20), ("Program Manager", 30)]
    labels = [t["label"] for t in suggest.titles("project man", rows)]
    assert labels[0] == "Project Manager"  # most postings first
    assert "Project Manager III" not in labels  # level numbers are not offered
    assert "Senior Project Manager" in labels  # a word inside the title also matches
    assert suggest.titles("p", rows) == []
    kw = [k["label"] for k in suggest.keywords("pm")]
    assert kw[:2] == ["PMI", "PMO"] or "PMP" in kw
    assert "PMP" in kw and "PMBOK" in kw
    assert suggest.keywords("zzzz") == []


def test_suggest_endpoint(search):
    client, _ = search
    kw = client.get("/api/v1/job-search/suggest", params={"kind": "keyword", "q": "pm"}).json()
    assert {"label": "PMP"} in kw
    assert isinstance(client.get("/api/v1/job-search/suggest", params={"kind": "title", "q": "proj"}).json(), list)


def test_empty_model_reply_does_not_crash_the_parsers():
    from app.services.discovery import web_search as ws

    assert ws.parse_items("") == []
    assert ws.parse_object("") == {}


def test_model_reply_text_is_always_a_string():
    from app.services.llm.client import reply_text

    assert reply_text(None) == ""
    assert reply_text("") == ""
    assert reply_text("[1]") == "[1]"
    assert reply_text([{"type": "text", "text": "[1]"}, {"type": "text", "text": "[2]"}]) == "[1][2]"
    assert reply_text([{"type": "other"}, "x"]) == "x"


def _save_posting(company, title, location, url):
    import time
    from app.services.jobcache.store import JobCache

    cache = JobCache()
    emp_id, _ = cache.upsert_employer("workday", f"{company}-id", company, "test")
    with cache.session() as db:
        db.execute(
            "INSERT INTO postings (employer_id, ext_id, title, location, url, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (emp_id, url[-8:], title, location, url, int(time.time()), int(time.time())),
        )


def _counting_resolver(monkeypatch, answers):
    ws = _resolver(monkeypatch, answers)
    calls = []
    real = ws.LLMClient.chat_completion

    async def counted(self, **kwargs):
        calls.append(kwargs)
        return await real(self, **kwargs)

    monkeypatch.setattr(ws.LLMClient, "chat_completion", counted)
    return ws, calls


def test_board_result_found_in_the_saved_lists_costs_no_lookup(monkeypatch):
    import asyncio

    ws, calls = _counting_resolver(monkeypatch, {})
    _save_posting("Acme Health", "Revenue Cycle Analyst", "Boston, MA", "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/R1")
    out, dropped = asyncio.run(ws.resolve_original_sources(_board_items()))
    by_title = {i["title"]: i for i in out}
    assert by_title["Revenue Cycle Analyst"]["url"] == "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/R1"
    assert len(calls) == 1  # only "Revenue Cycle Billing Analyst" was looked up; the other came from the saved lists
    assert dropped == 1


def test_saved_list_match_needs_one_clear_posting(monkeypatch):
    ws, calls = _counting_resolver(monkeypatch, {})
    _save_posting("Acme Health", "Revenue Cycle Analyst", "Boston, MA", "https://acme.wd5.myworkdayjobs.com/job/R1aaaa")
    _save_posting("Acme Health", "Revenue Cycle Analyst", "Denver, CO", "https://acme.wd5.myworkdayjobs.com/job/R2bbbb")
    item = {**_board_items()[0], "location": "Denver, CO"}
    assert ws.saved_original(item) == "https://acme.wd5.myworkdayjobs.com/job/R2bbbb"
    assert ws.saved_original({**item, "location": None}) is None  # two places, none named: not guessed
    assert ws.saved_original({**item, "company": "Other Corp"}) is None


def test_a_lookup_answer_is_remembered_for_a_day(monkeypatch):
    import asyncio

    ws, calls = _counting_resolver(monkeypatch, {"Revenue Cycle Analyst": "https://acme.example.com/jobs/1"})
    first, _ = asyncio.run(ws.resolve_original_sources(_board_items()))
    paid = len(calls)
    second, _ = asyncio.run(ws.resolve_original_sources(_board_items()))
    assert len(calls) == paid  # the second search paid for nothing: found and not-found answers were both remembered
    assert [i["url"] for i in first] == [i["url"] for i in second]


def test_an_old_remembered_answer_is_not_used(monkeypatch):
    from app.services.jobcache.store import JobCache

    cache = JobCache()
    cache.lookup_put("linkedin.com/jobs/view/1", "https://acme.example.com/jobs/1")
    assert cache.lookup_get("linkedin.com/jobs/view/1", 3600) == (True, "https://acme.example.com/jobs/1")
    assert cache.lookup_get("linkedin.com/jobs/view/1", -1) == (False, None)
    assert cache.lookup_get("indeed.com/nothing", 3600) == (False, None)


def test_paid_lookups_go_to_the_best_fits_first(monkeypatch):
    import asyncio

    ws, calls = _counting_resolver(monkeypatch, {})
    base = _board_items()[0]
    many = [{**base, "title": f"Role {n}", "fit": n / 10, "url": f"https://www.linkedin.com/jobs/view/{n}", "url_key": f"linkedin.com/jobs/view/{n}"}
            for n in range(5)]
    asyncio.run(ws.resolve_original_sources(many))
    asked = " ".join(json.dumps(c["messages"]) for c in calls)
    assert len(calls) == ws.MAX_RESOLVE == 2 and "Role 4" in asked and "Role 3" in asked and "Role 0" not in asked


def test_pay_with_cents_and_hourly_pay_are_checked_against_the_salary_minimum():
    from app.services.discovery.web_search import salary_midpoint, salary_floor

    floor = salary_floor(80000)
    for text in ("$43,800.00 - $51,100.00", "$17.71 - $24.28", "$50,070.00 - $60,730.00"):
        assert salary_midpoint(text) < floor, text
    for text in ("$75,275.20 - $109,553.60", "$76,300.00 - $92,100.00", "$39.00 - $49.63"):  # the last is hourly: about $92,000 a year
        assert salary_midpoint(text) >= floor, text


def _plan(**kw):
    from types import SimpleNamespace
    from app.services.jobcache import matcher

    base = dict(titles="consultant", location="Boston, MA", work_type="any", keywords="revenue cycle", target_salary=80000,
                require_salary=True, posted_within_days=None, exclude_companies=None)
    extra = kw.pop("extra", None)
    base.update(kw)
    return matcher.build_plan(SimpleNamespace(**base), extra)


def _row(title, pay_text=None, pay_mid=None, company="Acme Health", location="Boston, MA"):
    return {"title": title, "company": company, "location": location, "work_type": None, "pay_text": pay_text, "pay_mid": pay_mid, "posted_at": None}


def test_a_keyword_is_required_and_a_job_without_it_is_left_out():
    from app.services.jobcache import matcher

    plan = _plan(extra=None)
    assert matcher.score_row(plan, _row("Revenue Cycle Consultant")) is not None
    assert matcher.score_row(plan, _row("Epic Consultant")) is None  # no "revenue cycle" anywhere
    assert matcher.score_row(plan, _row("Cycle Consultant")) is None  # both words of the keyword are needed
    assert matcher.score_row(_plan(keywords=None), _row("Epic Consultant")) is not None  # no keyword asked: nothing required


def test_one_word_alternative_titles_are_not_used():
    from app.services.jobcache import matcher

    plan = _plan(keywords=None, target_salary=None, extra=["Specialist", "Analyst", "Revenue Cycle Advisor"])
    assert matcher.score_row(plan, _row("Registration Specialist")) is None
    assert matcher.score_row(plan, _row("Revenue Cycle Advisor")) is not None  # a two-word alternative still counts


def test_saved_pay_text_is_read_when_the_saved_number_is_missing():
    from app.services.jobcache import matcher

    plan = _plan(keywords=None, extra=None)
    assert matcher.score_row(plan, _row("Consultant", pay_text="$43,800.00 - $51,100.00")) is None
    assert matcher.score_row(plan, _row("Consultant", pay_text="$17.71 - $24.28")) is None
    assert matcher.score_row(plan, _row("Consultant", pay_text="$90,000.00 - $110,000.00")) is not None
    assert matcher.score_row(plan, _row("Consultant", pay_text=None)) is not None  # no pay stated: kept here, removed by "pay must be listed"


def test_a_recently_read_saved_list_is_not_asked_again(monkeypatch):
    import asyncio
    import time
    from app.services.discovery import ats, web_search as ws

    asked = []

    async def fake(url, client, boards):
        asked.append(url)
        return ats.AtsInfo(live=True, checked=True)

    monkeypatch.setattr(ws.ats, "inspect", fake)
    now = time.time()
    items = [
        {"title": "fresh", "url": "https://x.example.com/fresh", "read_at": now - 3600},
        {"title": "stale", "url": "https://x.example.com/stale", "read_at": now - 5 * 86400},
        {"title": "web", "url": "https://x.example.com/web"},
    ]
    kept, gone = asyncio.run(ws.enrich_from_ats(items))
    assert gone == 0 and len(kept) == 3
    assert asked == ["https://x.example.com/stale", "https://x.example.com/web"]
    assert items[0]["ats_checked"] is True and items[0]["ats_live"] is True


def test_pages_ask_for_many_results_and_check_enough_candidates():
    from app.schemas.job_search import JobSearchIn
    from app.services.discovery.web_search import _pool_size

    page_one = JobSearchIn(titles="revenue cycle manager", count=10)
    assert _pool_size(page_one) == 30  # unchanged for an ordinary search
    deep = JobSearchIn(titles="revenue cycle manager", count=190, more=True)  # opening page 20 loads everything up to it
    assert deep.count == 190 and _pool_size(deep) >= 190


def test_any_page_of_the_saved_matches_is_cut_from_one_ranked_list(monkeypatch):
    import asyncio
    from app.schemas.job_search import JobSearchIn
    from app.services.discovery import web_search as ws
    from app.services.jobcache import service as cache_service

    ranked = [
        {"title": f"Revenue Cycle Manager {i}", "company": "Acme Health", "location": "Boston, MA", "work_type": None, "salary_text": None,
         "posted_at": None, "summary": None, "url": f"https://acme.wd1.myworkdayjobs.com/en-US/c/job/Boston/Manager_R{i}", "url_key": f"k{i}",
         "grounded": True, "fit": 0.9 - i / 100, "employer_id": 1, "read_at": None}
        for i in range(25)
    ]

    async def fake_ranked(criteria):
        return ranked

    async def keep(items, *a, **k):
        return items, 0

    async def keep_dates(items, *a, **k):
        return items, 0

    monkeypatch.setattr(cache_service, "ranked_items", fake_ranked)
    monkeypatch.setattr(ws, "enrich_from_ats", keep)
    monkeypatch.setattr(ws, "fill_posted_dates", keep_dates)
    monkeypatch.setattr(ws, "drop_closed", keep)

    async def no_titles(titles):
        return []

    monkeypatch.setattr(cache_service, "expand_titles", no_titles)
    c = JobSearchIn(titles="revenue cycle manager", count=10, page=3)
    items, total = asyncio.run(ws.search_page(c, set(), 20))
    assert total == 25 and [i["title"] for i in items] == [f"Revenue Cycle Manager {n}" for n in range(20, 25)]
    assert all("fit" not in i and "read_at" not in i and i["fit_score"] is not None for i in items)
    # a job already in Jobs is left out of the count and the page
    from app.services.jobcache.keys import loose_keys
    known = set(loose_keys(ranked[0]["url"]))
    items, total = asyncio.run(ws.search_page(c, known, 0))
    assert total == 24 and items[0]["title"].endswith(" 1")


def test_sort_orders_the_whole_list_and_the_count_never_changes(monkeypatch):
    import asyncio
    import datetime as dt
    from app.schemas.job_search import JobSearchIn
    from app.services.discovery import web_search as ws
    from app.services.jobcache import service as cache_service

    days = [5, None, 1, 9, 3]
    ranked = [
        {"title": f"Analyst {i}", "company": "Acme Health", "location": "Boston, MA", "work_type": None, "salary_text": None,
         "posted_at": (dt.date(2026, 10, 20) - dt.timedelta(days=d)) if d is not None else None, "summary": None,
         "url": f"https://acme.wd1.myworkdayjobs.com/en-US/c/job/Boston/Analyst_R{i}", "url_key": f"k{i}", "grounded": True,
         "fit": 0.9 - i / 100, "employer_id": 1, "read_at": None}
        for i, d in enumerate(days)
    ]

    async def fake_ranked(criteria):
        return ranked

    async def keep(items, *a, **k):
        return items, 0

    async def no_titles(titles):
        return []

    monkeypatch.setattr(cache_service, "ranked_items", fake_ranked)
    monkeypatch.setattr(cache_service, "expand_titles", no_titles)
    for name in ("enrich_from_ats", "fill_posted_dates", "drop_closed"):
        monkeypatch.setattr(ws, name, keep)
    c = JobSearchIn(titles="analyst", count=10, page=1)
    newest, total_newest = asyncio.run(ws.search_page(c, set(), 0, sort="newest"))
    best, total_best = asyncio.run(ws.search_page(c, set(), 0, sort="search"))
    assert total_newest == total_best == 5
    assert [i["title"] for i in newest] == ["Analyst 2", "Analyst 4", "Analyst 0", "Analyst 3", "Analyst 1"]  # 1, 3, 5, 9 days ago, then no date
    assert [i["title"] for i in best][0] == "Analyst 0"
    _, counted = asyncio.run(ws.search_page(c, set(), 0, count_only=True))
    assert counted == 5
    scored, _ = asyncio.run(ws.search_page(c, set(), 0, sort="resume", resume_scores={"k3": 0.9, "k1": 0.4}))
    assert [i["title"] for i in scored][:2] == ["Analyst 3", "Analyst 1"]


def test_the_web_search_alone_ranks_its_finds_into_the_list_and_never_fails_the_page(search, monkeypatch):
    from app.services.discovery import web_search

    client, SessionLocal = search
    out = client.post("/api/v1/job-search/web", json={"titles": "revenue cycle analyst", "web": "only"})
    assert out.status_code == 200 and set(out.json()) == {"added", "total"}

    async def boom(*a, **k):
        raise RuntimeError("web search down")

    monkeypatch.setattr(web_search, "search_jobs_full", boom)
    broken = client.post("/api/v1/job-search/web", json={"titles": "revenue cycle analyst", "web": "only"})
    assert broken.status_code == 200 and broken.json()["added"] == 0


def test_a_page_is_filled_and_the_count_is_honest_when_jobs_fail_the_place_check(monkeypatch):
    import asyncio
    import datetime as dt
    from app.schemas.job_search import JobSearchIn
    from app.services.discovery import web_search as ws
    from app.services.jobcache import service as cache_service

    places = ["Santa Fe, NM", None, "Santa Fe, NM", "2 Locations", "Santa Fe, NM", "Santa Fe, NM", "Santa Fe, NM"]
    ranked = [
        {"title": f"Chef {i}", "company": "Acme", "location": p, "work_type": None, "salary_text": None, "posted_at": dt.date.today(), "summary": None,
         "url": f"https://acme.wd1.myworkdayjobs.com/en-US/c/job/x/Chef_R{i}", "url_key": f"k{i}", "grounded": True, "fit": 0.9 - i / 100, "employer_id": 1, "read_at": None}
        for i, p in enumerate(places)
    ]
    dropped: list[set] = []

    async def fake_ranked(criteria):
        return ranked

    async def keep(items, *a, **k):
        return items, 0

    async def no_titles(titles):
        return []

    async def fake_drop(criteria, urls):
        dropped.append(urls)

    monkeypatch.setattr(cache_service, "ranked_items", fake_ranked)
    monkeypatch.setattr(cache_service, "expand_titles", no_titles)
    monkeypatch.setattr(cache_service, "drop_from_ranked", fake_drop)
    ws._PAGE_CHECKED.clear()
    ws._PAGE_TOTAL.clear()
    for name in ("enrich_from_ats", "fill_posted_dates", "drop_closed"):
        monkeypatch.setattr(ws, name, keep)
    c = JobSearchIn(titles="chef", location="Santa Fe, NM", count=3, page=1)
    items, total = asyncio.run(ws.search_page(c, set(), 0))
    assert [i["title"] for i in items] == ["Chef 0", "Chef 2", "Chef 4"]  # the full page: the two jobs that name no place were skipped
    assert total == 5 and dropped and len(dropped[0]) == 2
    _, counted = asyncio.run(ws.search_page(c, set(), 0, count_only=True))
    assert counted == 5


def test_no_company_site_is_asked_about_more_than_three_jobs_at_once(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from app.services.discovery import ats, web_search

    now = {"a": 0, "b": 0}
    peak = {"a": 0, "b": 0}

    async def fake_inspect(url, client, boards):
        key = "a" if "//a." in url else "b"
        now[key] += 1
        peak[key] = max(peak[key], now[key])
        await asyncio.sleep(0.01)
        now[key] -= 1
        return SimpleNamespace(checked=True, live=True, posted=None, pay=None, places=None)

    monkeypatch.setattr(ats, "inspect", fake_inspect)
    items = [{"url": f"https://{h}.example.com/job/{n}", "title": "x"} for h in "ab" for n in range(12)]
    asyncio.run(web_search.enrich_from_ats(items))
    assert 1 <= peak["a"] <= web_search.ENRICH_PER_HOST and 1 <= peak["b"] <= web_search.ENRICH_PER_HOST
