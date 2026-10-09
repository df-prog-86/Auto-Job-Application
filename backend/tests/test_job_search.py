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
    {"title": "Billing Analyst", "company": "Beta Care", "location": "Boston, MA", "work_type": "hybrid", "salary": None, "posted": "2020-01-01",
     "url": "https://jobs.betacare.com/postings/42", "summary": "Own claim edits."},
    {"title": "No link", "company": "Gamma", "location": None, "work_type": "unknown", "salary": None,
     "url": "not a url", "summary": "x"},
    {"title": "Already saved", "company": "Delta", "location": None, "work_type": "remote", "salary": None,
     "url": "https://delta.example.com/jobs/7", "summary": "x"},
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

    async def no_dates(items, within_days):
        return items, 0  # tests never visit real sites

    monkeypatch.setattr(web_search, "check_live", unknown)
    monkeypatch.setattr(web_search, "fill_posted_dates", no_dates)

    async def no_ats(items):
        return items, 0

    monkeypatch.setattr(web_search, "enrich_from_ats", no_ats)
    monkeypatch.setattr(web_search.LLMClient, "chat_completion", fake)
    return app_and_db


def _saved_job(SessionLocal) -> None:
    from app.models.jobs import Job

    now = dt.datetime.now(dt.timezone.utc)
    with SessionLocal() as db:
        db.add(Job(canonical_job_key="k-delta", company="Delta", normalized_company="delta", title="Analyst",
                   normalized_title="analyst", canonical_application_url="https://delta.example.com/jobs/7",
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
    assert set(by_title) == {"Revenue Cycle Analyst", "Billing Analyst"}
    assert by_title["Revenue Cycle Analyst"]["grounded"] is True  # the search engine returned this link
    assert "utm_source" not in by_title["Revenue Cycle Analyst"]["url"]
    assert by_title["Billing Analyst"]["grounded"] is False

    again = client.post("/api/v1/job-search/run", json={"titles": "revenue cycle analyst"}).json()
    assert again["found"] == 0 and len(again["results"]) == 2  # nothing is duplicated


def test_add_uses_the_summary_when_the_page_cannot_be_read_and_remove_hides_a_result(search, monkeypatch):
    from app.services.discovery import manual_extraction

    client, SessionLocal = search
    _saved_job(SessionLocal)  # the mocked search also returns a posting that is already saved

    async def blocked(url):
        raise manual_extraction.ManualExtractionError("blocked")

    monkeypatch.setattr(manual_extraction, "fetch_page", blocked)
    out = client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()
    first = next(r for r in out["results"] if r["title"] == "Billing Analyst")
    other = next(r for r in out["results"] if r["title"] == "Revenue Cycle Analyst")

    added = client.post(f"/api/v1/job-search/results/{first['id']}/add").json()
    assert added["from_summary"] is True and added["job"]["title"] == "Billing Analyst"
    assert "Billing Analyst" in [j["title"] for j in client.get("/api/v1/jobs").json()]

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
    assert "Already saved" not in titles and "Billing Analyst" in titles


def test_clearly_closed_postings_are_dropped_but_unclear_ones_stay(search, monkeypatch):
    from app.services.discovery import web_search

    client, _ = search

    async def verdict(url):
        return False if "acme" in url else None  # Acme is closed; the rest could not be checked

    monkeypatch.setattr(web_search, "check_live", verdict)
    out = client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()
    assert "Revenue Cycle Analyst" not in [r["title"] for r in out["results"]]
    assert "Billing Analyst" in [r["title"] for r in out["results"]]
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
    assert salary_midpoint("$45 - $60 per hour") is None and salary_midpoint("Competitive") is None

    client, _ = search
    low = client.post("/api/v1/job-search/run", json={"titles": "analyst", "target_salary": 100000}).json()
    titles = [r["title"] for r in low["results"]]
    assert "Revenue Cycle Analyst" not in titles  # posted $85,000 is under the $95,000 floor
    assert "Billing Analyst" in titles  # no posted pay stays unless the pay box is ticked


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
    assert "Billing Analyst" not in [r["title"] for r in out["results"]]  # posted in 2020


_PROFILE = {
    "extraction": {
        "contact": {"name": "Jane Doe", "email": "jane@example.com"},
        "employment": [
            {"employer": "Acme Corp", "title": "Billing Analyst", "start_date": "2021-04", "end_date": None,
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
        {**base, "title": "Billing Analyst", "url": "https://www.indeed.com/viewjob?jk=2", "url_key": "indeed.com/viewjob?jk=2"},
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
    assert "Billing Analyst" not in by_title  # no original found, so the board link is dropped
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
    ws = _resolver(monkeypatch, {"Revenue Cycle Analyst": same, "Billing Analyst": same})
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


def test_date_window_drops_old_postings_but_keeps_undated_ones(monkeypatch):
    import asyncio
    import datetime as dt
    from app.services.discovery import web_search as ws

    async def no_visit(self, *a, **k):
        raise RuntimeError("tests never visit real sites")

    monkeypatch.setattr(ws.httpx.AsyncClient, "get", no_visit)
    today = dt.date.today()
    mk = lambda n, d: {"title": n, "url": f"https://jobs.example.com/{n}", "posted_at": d}
    items = [mk("new", today - dt.timedelta(days=3)), mk("old", today - dt.timedelta(days=40)), mk("undated", None)]
    kept, dropped = asyncio.run(ws.fill_posted_dates(items, 14))
    assert [i["title"] for i in kept] == ["new", "undated"] and dropped == 1


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
    assert len(seen) == 3
    assert any(p.get("include_domains") == ["*.myworkdayjobs.com"] for p in seen)
    assert any("jobs.ashbyhq.com" in p.get("include_domains", []) for p in seen)
    web = [p for p in seen if "exclude_domains" in p][0]
    assert "linkedin.com" in web["exclude_domains"] and all(p["engine"] == "exa" for p in seen)


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

    site = {"title": "Revenue Cycle Consultant", "company": "Huron", "url": "https://huron.com/careers/1", "grounded": True}
    ats = {"title": "Revenue Cycle  Consultant", "company": "HURON", "url": "https://huron.wd1.myworkdayjobs.com/en-US/c/job/R1", "grounded": False}
    other = {"title": "Billing Analyst", "company": "Huron", "url": "https://huron.com/careers/2", "grounded": False}
    assert merge_same_jobs([site, ats, other]) == [ats, other]


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
    assert is_board_url("https://www.somenewjobsite.com/view/1", "Huron")  # not listed, but named like a jobs site
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
