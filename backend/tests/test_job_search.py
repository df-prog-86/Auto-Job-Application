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

    monkeypatch.setattr(web_search, "check_live", unknown)
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
                             description_html="<p>Denial work and payer trends. 3+ years.</p>", application_url=kwargs["url"])

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


def test_match_score_needs_a_profile_and_says_when_only_the_summary_was_used(search, monkeypatch):
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
            from app.services.llm.schemas import ResumeJobMatchResult

            return ResumeJobMatchResult(match_percentage=40, summary="Partial.", gaps=[])

    monkeypatch.setattr(manual_extraction, "fetch_page", blocked)
    monkeypatch.setattr("app.services.qualification.pipeline.ModelRouter", _Router)
    scored = client.post(f"/api/v1/job-search/results/{first['id']}/score").json()
    assert scored["match_score"] == 0.4 and scored["match_from_page"] is False
