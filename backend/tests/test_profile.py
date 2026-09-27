"""
Milestone 2 acceptance coverage. The resume-parse endpoint needs a real LLM
provider (none is configured in tests, matching the honest "no provider
configured" default) — that path is tested for its 503 behavior, not a full
parse. The rest of the pipeline (commit -> retrieve -> update, answers,
experience summary) is tested end-to-end via a hand-built payload that
matches exactly what a reviewed parse result would look like, so these
tests exercise the same commit code path a real upload would.
"""

from __future__ import annotations

import io

import docx


def _fake_docx_bytes() -> bytes:
    document = docx.Document()
    document.add_paragraph("Jane Doe")
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def test_resume_parse_without_llm_configured_returns_503(app_and_db):
    client, _ = app_and_db
    files = {"file": ("resume.docx", _fake_docx_bytes(), "application/octet-stream")}
    resp = client.post("/api/v1/profile/resume/parse", files=files)
    assert resp.status_code == 503
    assert "LLM provider" in resp.json()["detail"]


def test_resume_parse_rejects_invalid_file(app_and_db):
    client, _ = app_and_db
    files = {"file": ("resume.pdf", b"not a real pdf", "application/octet-stream")}
    resp = client.post("/api/v1/profile/resume/parse", files=files)
    assert resp.status_code == 400


_COMMIT_PAYLOAD = {
    "extraction": {
        "contact": {"name": "Jane Doe", "email": "jane@example.com"},
        "employment": [
            {
                "employer": "Acme Corp",
                "title": "Senior Data Analyst",
                "start_date": "2021-04",
                "end_date": None,
                "source_text": "Built Power BI dashboards using SQL.",
            }
        ],
        "education": [],
        "skills": ["SQL", "Power BI"],
        "certifications": [],
        "projects": [],
    },
    "approved_claims": [
        {
            "category": "experience",
            "canonical_text": "Worked as Senior Data Analyst at Acme Corp.",
            "employer": "Acme Corp",
            "associated_role": "Senior Data Analyst",
            "skills": ["SQL"],
            "start_date": "2021-04-01",
            "end_date": None,
            "metrics": {},
            "source_section": "employment",
            "source_text": "Built Power BI dashboards using SQL.",
        }
    ],
    "resume_filename": "resume.docx",
}


def test_profile_commit_get_and_patch(app_and_db):
    client, _ = app_and_db

    commit_resp = client.post("/api/v1/profile/commit", json=_COMMIT_PAYLOAD)
    assert commit_resp.status_code == 200
    profile = commit_resp.json()
    assert profile["name"] == "Jane Doe"
    assert profile["email"] == "jane@example.com"

    get_resp = client.get("/api/v1/profile")
    assert get_resp.status_code == 200
    assert get_resp.json()["email"] == "jane@example.com"

    patch_resp = client.patch("/api/v1/profile", json={"phone": "555-0100"})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["phone"] == "555-0100"


def test_profile_not_found_before_commit(app_and_db):
    client, _ = app_and_db
    resp = client.get("/api/v1/profile")
    assert resp.status_code == 404


def test_answers_upsert_and_list(app_and_db):
    client, _ = app_and_db
    client.post("/api/v1/profile/commit", json=_COMMIT_PAYLOAD)

    put_resp = client.put(
        "/api/v1/profile/answers/work_authorization",
        json={"value_type": "bool", "value": True, "user_confirmed": True},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["value"] is True

    list_resp = client.get("/api/v1/profile/answers")
    assert list_resp.status_code == 200
    keys = [a["answer_key"] for a in list_resp.json()]
    assert "work_authorization" in keys


def test_experience_summary_reflects_committed_claims(app_and_db):
    client, _ = app_and_db
    client.post("/api/v1/profile/commit", json=_COMMIT_PAYLOAD)

    resp = client.get("/api/v1/profile/experience-summary")
    assert resp.status_code == 200
    entries = {e["skill"]: e for e in resp.json()["entries"]}
    assert "SQL" in entries
    assert entries["SQL"]["total_years"] > 0
