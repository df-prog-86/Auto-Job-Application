"""Job Search: web search results, de-duplication, Add to jobs, Remove."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from app.services.llm.client import ChatCompletionResult

ITEMS = [
    {"title": "Revenue Cycle Analyst", "company": "Acme Health", "location": "Remote, US", "work_type": "remote",
     "salary": "$85,000", "url": "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/Remote/Analyst_R1?utm_source=x",
     "summary": "Analyze denials and payer trends."},
    {"title": "Billing Analyst", "company": "Beta Care", "location": "Boston, MA", "work_type": "hybrid", "salary": None,
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

    client, _ = search

    async def blocked(url):
        raise manual_extraction.ManualExtractionError("blocked")

    monkeypatch.setattr(manual_extraction, "fetch_page", blocked)
    out = client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()
    first = next(r for r in out["results"] if r["title"] == "Billing Analyst")
    other = next(r for r in out["results"] if r["title"] == "Revenue Cycle Analyst")

    added = client.post(f"/api/v1/job-search/results/{first['id']}/add").json()
    assert added["from_summary"] is True and added["job"]["title"] == "Billing Analyst"
    assert [j["title"] for j in client.get("/api/v1/jobs").json()] == ["Billing Analyst"]

    assert client.post(f"/api/v1/job-search/results/{other['id']}/remove").json()["status"] == "removed"
    assert client.get("/api/v1/job-search/results").json()["results"] == []
    assert client.post(f"/api/v1/job-search/results/{other['id']}/add").status_code == 404  # gone from the list

    # A removed posting is not offered again by a later search.
    assert client.post("/api/v1/job-search/run", json={"titles": "analyst"}).json()["found"] == 0


def test_clear_removes_everything_waiting(search):
    client, _ = search
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
