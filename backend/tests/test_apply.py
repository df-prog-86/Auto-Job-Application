"""Extension fill flow (context + report) and the Needs Attention list."""

from __future__ import annotations

import datetime as dt

_COMMIT = {
    "extraction": {
        "contact": {"name": "Jane Q Doe", "email": "jane@example.com", "phone": "555-0100", "location": "Boston, MA"},
        "employment": [],
        "education": [],
        "skills": [],
        "certifications": [],
        "projects": [],
    },
    "approved_claims": [],
    "resume_filename": "resume.docx",
}


def _token(client) -> dict:
    secret = client.post("/api/v1/system/pairing-secret").json()["pairing_secret"]
    token = client.post(
        "/api/v1/system/pair", json={"pairing_secret": secret, "extension_origin": "chrome-extension://t"}
    ).json()["extension_token"]
    return {"X-Extension-Token": token}


def _job(SessionLocal, *, url="https://job-boards.greenhouse.io/acme/jobs/123", proceeding=True, resume=True) -> int:
    from app.models.documents import GeneratedDocument
    from app.models.jobs import Job

    now = dt.datetime.now(dt.timezone.utc)
    with SessionLocal() as db:
        job = Job(
            canonical_job_key=f"k-{url}",
            company="Acme",
            normalized_company="acme",
            title="Analyst",
            normalized_title="analyst",
            canonical_application_url=url,
            first_seen=now,
            last_seen=now,
            application_status="proceeding" if proceeding else "not_started",
        )
        db.add(job)
        db.flush()
        if resume:
            db.add(
                GeneratedDocument(
                    job_id=job.id,
                    document_type="resume",
                    local_path="/tmp/Jane Doe_Resume_Acme_2026.docx",
                    format="docx",
                    generated_at=now,
                    template_version="t",
                    content_hash="h",
                )
            )
        db.commit()
        return job.id


def test_apply_endpoints_require_the_extension_token(app_and_db):
    client, _ = app_and_db
    assert client.post("/api/v1/apply/context", json={"url": "https://x.com"}).status_code == 401
    assert client.post("/api/v1/apply/report", json={"job_id": 1}).status_code == 401


def test_context_needs_a_profile(app_and_db):
    client, _ = app_and_db
    out = client.post("/api/v1/apply/context", json={"url": "https://x.com"}, headers=_token(client)).json()
    assert out["candidate"] is None and "Profile" in out["problem"]


def test_context_matches_job_and_returns_facts_answers_and_resume(app_and_db):
    client, SessionLocal = app_and_db
    client.post("/api/v1/profile/commit", json=_COMMIT)
    client.put("/api/v1/profile/answers/work_authorization", json={"value_type": "str", "value": "US citizen"})
    client.put("/api/v1/profile/answers/sponsorship_required", json={"value_type": "bool", "value": False})
    client.put("/api/v1/profile/answers/q:why do you want this role", json={"value_type": "str", "value": "Mission fit."})
    job_id = _job(SessionLocal)
    headers = _token(client)

    out = client.post(
        "/api/v1/apply/context",
        json={"url": "https://job-boards.greenhouse.io/acme/jobs/123?gh_src=abc#app"},
        headers=headers,
    ).json()
    assert out["problem"] is None
    assert out["job"]["id"] == job_id
    assert out["candidate"]["first_name"] == "Jane"
    assert out["candidate"]["last_name"] == "Q Doe"
    assert out["candidate"]["email"] == "jane@example.com"
    assert out["answers"] == {"work_authorization": "US citizen", "sponsorship_required": False}
    assert out["learned_answers"] == {"why do you want this role": "Mission fit."}
    assert out["resume"]["filename"] == "Jane Doe_Resume_Acme_2026.docx"


def test_context_stops_before_proceed_or_resume(app_and_db):
    client, SessionLocal = app_and_db
    client.post("/api/v1/profile/commit", json=_COMMIT)
    headers = _token(client)
    _job(SessionLocal, url="https://a.com/one", proceeding=False)
    _job(SessionLocal, url="https://a.com/two", resume=False)

    not_proceeding = client.post("/api/v1/apply/context", json={"url": "https://a.com/one"}, headers=headers).json()
    assert "Proceed" in not_proceeding["problem"] and not_proceeding["candidate"] is None

    no_resume = client.post("/api/v1/apply/context", json={"url": "https://a.com/two"}, headers=headers).json()
    assert "tailored resume" in no_resume["problem"] and no_resume["candidate"] is None


def test_context_lists_choices_when_page_is_unknown(app_and_db):
    client, SessionLocal = app_and_db
    client.post("/api/v1/profile/commit", json=_COMMIT)
    _job(SessionLocal, url="https://a.com/one")
    out = client.post("/api/v1/apply/context", json={"url": "https://elsewhere.com/x"}, headers=_token(client)).json()
    assert out["job"] is None and len(out["candidates"]) == 1 and "pick" in out["problem"].lower()


def test_report_creates_questions_once_and_needs_attention_flow(app_and_db):
    client, SessionLocal = app_and_db
    client.post("/api/v1/profile/commit", json=_COMMIT)
    job_id = _job(SessionLocal)
    headers = _token(client)
    body = {
        "job_id": job_id,
        "page_url": "https://job-boards.greenhouse.io/acme/jobs/123",
        "filled_count": 5,
        "flagged": [
            {"label": "Why do you want to work here? *", "field_type": "textarea", "required": True},
            {"label": "How did you hear about us?", "field_type": "select", "options": ["Referral", "Other"]},
        ],
    }
    assert client.post("/api/v1/apply/report", json=body, headers=headers).status_code == 204
    assert client.post("/api/v1/apply/report", json=body, headers=headers).status_code == 204  # re-run: no duplicates

    open_items = client.get("/api/v1/needs-attention").json()
    assert len(open_items) == 2
    why = next(i for i in open_items if i["label"].startswith("Why do you"))
    assert why["company"] == "Acme" and why["required"] is True

    answered = client.post(f"/api/v1/needs-attention/{why['id']}/answer", json={"answer": "Mission fit."})
    assert answered.status_code == 200 and answered.json()["status"] == "answered"
    assert len(client.get("/api/v1/needs-attention").json()) == 1

    # The answer is remembered and handed back on the next fill, for any job.
    ctx = client.post(
        "/api/v1/apply/context", json={"url": "https://job-boards.greenhouse.io/acme/jobs/123"}, headers=headers
    ).json()
    assert ctx["learned_answers"] == {"why do you want to work here": "Mission fit."}

    # Answered questions don't come back when Fill runs again.
    client.post("/api/v1/apply/report", json=body, headers=headers)
    assert len(client.get("/api/v1/needs-attention").json()) == 1

    other = client.get("/api/v1/needs-attention").json()[0]
    assert client.post(f"/api/v1/needs-attention/{other['id']}/dismiss").json()["status"] == "dismissed"
    assert client.get("/api/v1/needs-attention").json() == []
    assert client.post(f"/api/v1/needs-attention/{why['id']}/answer", json={"answer": "  "}).status_code == 422


def test_deleting_a_job_removes_its_questions(app_and_db):
    client, SessionLocal = app_and_db
    client.post("/api/v1/profile/commit", json=_COMMIT)
    job_id = _job(SessionLocal)
    client.post(
        "/api/v1/apply/report",
        json={"job_id": job_id, "flagged": [{"label": "Anything else?"}]},
        headers=_token(client),
    )
    assert len(client.get("/api/v1/needs-attention").json()) == 1
    assert client.delete(f"/api/v1/jobs/{job_id}").status_code == 204
    assert client.get("/api/v1/needs-attention").json() == []
