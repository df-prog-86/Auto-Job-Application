"""
Job intake (paste-a-URL), scoring, the Proceed gate, delete/undo, and resume
tailoring, end to end through the API. No test touches the real network or a
real LLM: page fetching and the model router are replaced with fakes, and
every test uses its own temporary database and folders.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from urllib.parse import unquote

import pytest
from docx import Document

from app.config import settings
from app.models.documents import GeneratedDocument
from app.services.discovery import manual_extraction
from app.services.discovery.manual_extraction import FetchedPage, ManualExtractionError
from app.services.llm.schemas import (
    JobPostingExtraction,
    PlannedBlock,
    PlannedBullet,
    ResumeJobMatchResult,
    TailorPlan,
)


def _jsonld(title="Data Analyst", company="Globex", url="https://example.com/jobs/1") -> str:
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": title,
            "hiringOrganization": {"@type": "Organization", "name": company},
            "description": "<p>Analyze data with SQL. 3+ years of experience required.</p>",
            "jobLocation": {"address": {"addressLocality": "Boston", "addressRegion": "MA"}},
            "url": url,
        }
    )


def _add_job(client, monkeypatch, **kwargs) -> dict:
    """Adds a job by link with the page fetch faked; returns the response JSON."""
    block = _jsonld(**kwargs)

    async def fake_fetch(url: str) -> FetchedPage:
        return FetchedPage(url=url, json_ld_blocks=[block], body_text="", title="Job")

    monkeypatch.setattr(manual_extraction, "fetch_page", fake_fetch)
    resp = client.post("/api/v1/jobs/manual", json={"url": kwargs.get("url", "https://example.com/jobs/1")})
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def docs_dir(tmp_path, monkeypatch):
    """Points generated documents (and the master resume folder beside it) at a temp dir."""
    monkeypatch.setattr(settings, "GENERATED_DOCUMENTS_DIR", str(tmp_path / "generated_documents"))
    return tmp_path


_PROFILE = {
    "extraction": {
        "contact": {"name": "Jane Doe", "email": "jane@example.com"},
        "employment": [],
        "education": [],
        "skills": [],
        "certifications": [],
        "projects": [],
    },
    "approved_claims": [],
    "resume_filename": "resume.docx",
}


# --- structured data extraction (pure functions) ---------------------------


def test_structured_data_extracts_a_job_posting():
    posting = manual_extraction.extract_from_structured_data([_jsonld()], "https://example.com/jobs/1")
    assert posting is not None
    assert posting.title == "Data Analyst"
    assert posting.company == "Globex"
    assert posting.location == "Boston, MA"


def test_structured_data_requires_title_and_company():
    no_company = json.dumps({"@type": "JobPosting", "title": "Analyst"})
    no_title = json.dumps({"@type": "JobPosting", "hiringOrganization": {"name": "Globex"}})
    assert manual_extraction.extract_from_structured_data([no_company], "u") is None
    assert manual_extraction.extract_from_structured_data([no_title], "u") is None


def test_structured_data_handles_graph_and_ignores_other_types():
    graph = json.dumps({"@graph": [{"@type": "WebSite"}, json.loads(_jsonld())]})
    other = json.dumps({"@type": "Article", "title": "News", "hiringOrganization": {"name": "X"}})
    assert manual_extraction.extract_from_structured_data([graph], "u") is not None
    assert manual_extraction.extract_from_structured_data([other, "not json"], "u") is None


class _FakeExtractionRouter:
    def __init__(self, extraction: JobPostingExtraction):
        self._extraction = extraction

    def __call__(self, db):
        return self

    async def get_structured(self, **kwargs):
        return self._extraction


async def test_llm_fallback_refuses_pages_that_are_not_job_postings(monkeypatch):
    fake = _FakeExtractionRouter(JobPostingExtraction(is_job_posting=False))
    monkeypatch.setattr(manual_extraction, "ModelRouter", fake)
    with pytest.raises(ManualExtractionError):
        await manual_extraction.extract_job_posting(
            None, url="https://example.com/news", json_ld_blocks=[], body_text="Some article text", page_title="News"
        )


async def test_llm_fallback_never_accepts_a_posting_without_title_and_company(monkeypatch):
    fake = _FakeExtractionRouter(JobPostingExtraction(is_job_posting=True, title="Analyst", company=None))
    monkeypatch.setattr(manual_extraction, "ModelRouter", fake)
    with pytest.raises(ManualExtractionError):
        await manual_extraction.extract_job_posting(
            None, url="https://example.com/x", json_ld_blocks=[], body_text="text", page_title=None
        )


async def test_llm_fallback_accepts_a_real_posting(monkeypatch):
    fake = _FakeExtractionRouter(
        JobPostingExtraction(is_job_posting=True, title="Analyst", company="Globex", description="Do things")
    )
    monkeypatch.setattr(manual_extraction, "ModelRouter", fake)
    posting = await manual_extraction.extract_job_posting(
        None, url="https://example.com/x", json_ld_blocks=[], body_text="text", page_title=None
    )
    assert (posting.title, posting.company) == ("Analyst", "Globex")


# --- adding, listing, duplicates ---------------------------------------------


def test_add_job_by_link_and_list(app_and_db, monkeypatch):
    client, _ = app_and_db
    job = _add_job(client, monkeypatch)
    assert job["title"] == "Data Analyst"
    assert job["company"] == "Globex"
    assert job["application_status"] == "not_started"
    assert job["evaluation"] is None
    assert job["already_existed"] is False

    listed = client.get("/api/v1/jobs").json()
    assert [j["id"] for j in listed] == [job["id"]]


def test_adding_the_same_job_twice_says_so_and_keeps_one_row(app_and_db, monkeypatch):
    client, _ = app_and_db
    first = _add_job(client, monkeypatch)
    second = _add_job(client, monkeypatch)
    assert second["id"] == first["id"]
    assert second["already_existed"] is True
    assert len(client.get("/api/v1/jobs").json()) == 1


def test_page_that_is_not_a_job_is_rejected_cleanly(app_and_db, monkeypatch):
    client, _ = app_and_db

    async def fake_fetch(url: str) -> FetchedPage:
        return FetchedPage(url=url, json_ld_blocks=[], body_text="An article about weather.", title="News")

    monkeypatch.setattr(manual_extraction, "fetch_page", fake_fetch)
    resp = client.post("/api/v1/jobs/manual", json={"url": "https://example.com/news"})
    assert resp.status_code == 422
    assert client.get("/api/v1/jobs").json() == []


# --- scoring -----------------------------------------------------------------


class _FakeMatchRouter:
    def __init__(self, db):
        pass

    async def get_structured(self, **kwargs):
        return ResumeJobMatchResult(
            match_percentage=72, summary="Good SQL fit, short on years.", gaps=["3+ years of experience"]
        )


def test_scoring_stores_a_simple_result(app_and_db, monkeypatch):
    client, _ = app_and_db
    job = _add_job(client, monkeypatch)
    monkeypatch.setattr("app.services.qualification.pipeline.ModelRouter", _FakeMatchRouter)

    resp = client.post(f"/api/v1/jobs/{job['id']}/qualify")
    assert resp.status_code == 200
    evaluation = resp.json()["evaluation"]
    assert evaluation["overall_score"] == 0.72
    assert evaluation["summary"] == "Good SQL fit, short on years."
    assert evaluation["gaps"] == ["3+ years of experience"]

    again = client.post(f"/api/v1/jobs/{job['id']}/qualify")
    assert again.status_code == 200
    assert again.json()["evaluation"]["overall_score"] == 0.72  # re-scoring updates, not duplicates


def test_scoring_without_an_llm_is_a_clear_error_not_a_crash(app_and_db, monkeypatch):
    client, _ = app_and_db
    job = _add_job(client, monkeypatch)
    resp = client.post(f"/api/v1/jobs/{job['id']}/qualify")
    assert resp.status_code == 502
    assert client.get("/api/v1/jobs").json()[0]["evaluation"] is None


def test_adding_a_job_never_scores_it(app_and_db, monkeypatch):
    client, _ = app_and_db
    called = []

    class _Boom(_FakeMatchRouter):
        async def get_structured(self, **kwargs):
            called.append(1)
            return await super().get_structured(**kwargs)

    monkeypatch.setattr("app.services.qualification.pipeline.ModelRouter", _Boom)
    _add_job(client, monkeypatch)
    assert called == []


# --- proceed / undo / delete -------------------------------------------------


def test_proceed_and_undo(app_and_db, monkeypatch):
    client, _ = app_and_db
    job = _add_job(client, monkeypatch)
    assert client.post(f"/api/v1/jobs/{job['id']}/proceed").json()["application_status"] == "proceeding"
    assert client.post(f"/api/v1/jobs/{job['id']}/unproceed").json()["application_status"] == "not_started"
    assert client.post("/api/v1/jobs/9999/unproceed").status_code == 404


def test_delete_job_removes_it_and_its_generated_files(app_and_db, monkeypatch, docs_dir):
    client, SessionLocal = app_and_db
    job = _add_job(client, monkeypatch)

    inside = docs_dir / "generated_documents" / f"job_{job['id']}" / "resume.docx"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"x")
    with SessionLocal() as db:
        db.add(
            GeneratedDocument(
                job_id=job["id"],
                document_type="resume",
                local_path=str(inside),
                format="docx",
                generated_at=dt.datetime.now(dt.timezone.utc),
                template_version="t",
                source_claim_ids=[],
                content_hash="h",
            )
        )
        db.commit()

    assert client.delete(f"/api/v1/jobs/{job['id']}").status_code == 204
    assert client.get(f"/api/v1/jobs/{job['id']}").status_code == 404
    assert not inside.exists()
    assert client.delete(f"/api/v1/jobs/{job['id']}").status_code == 404


def test_delete_never_removes_files_outside_the_documents_folder(app_and_db, monkeypatch, docs_dir):
    client, SessionLocal = app_and_db
    job = _add_job(client, monkeypatch)
    outside = docs_dir / "important.txt"
    outside.write_text("keep me")
    with SessionLocal() as db:
        db.add(
            GeneratedDocument(
                job_id=job["id"],
                document_type="resume",
                local_path=str(outside),
                format="txt",
                generated_at=dt.datetime.now(dt.timezone.utc),
                template_version="t",
                source_claim_ids=[],
                content_hash="h",
            )
        )
        db.commit()

    assert client.delete(f"/api/v1/jobs/{job['id']}").status_code == 204
    assert outside.exists()


# --- tailoring ---------------------------------------------------------------

_BULLETS = ["Reduced report time by 40% using SQL", "Led a team of 5 analysts", "Built Tableau dashboards"]


def _write_master(docs_dir) -> bytes:
    doc = Document()
    doc.add_heading("Jane Doe", level=1)
    doc.add_paragraph("Analyst, Acme | 2020 – Present")
    for text in _BULLETS:
        doc.add_paragraph(text, style="List Bullet")
    master_dir = docs_dir / "master_resume"
    master_dir.mkdir(parents=True, exist_ok=True)
    path = master_dir / "master.docx"
    doc.save(str(path))
    return path.read_bytes()


class _FakePlanRouter:
    """Returns the plan it was built with for every call."""

    plan: TailorPlan

    def __init__(self, db):
        pass

    async def get_structured(self, **kwargs):
        return type(self).plan


def _plan(order: list[int], changelog=None) -> TailorPlan:
    return TailorPlan(
        blocks=[PlannedBlock(block_id=0, bullets=[PlannedBullet(bullet_id=i, text=_BULLETS[i]) for i in order])],
        changelog=changelog or [],
    )


def _docx_bullets(content: bytes) -> list[str]:
    return [p.text for p in Document(io.BytesIO(content)).paragraphs if p.style.name == "List Bullet"]


def test_tailoring_requires_proceed_first(app_and_db, monkeypatch, docs_dir):
    client, _ = app_and_db
    job = _add_job(client, monkeypatch)
    assert client.post(f"/api/v1/jobs/{job['id']}/tailor").status_code == 409


def test_tailoring_without_a_master_explains_what_to_do(app_and_db, monkeypatch, docs_dir):
    client, _ = app_and_db
    job = _add_job(client, monkeypatch)
    client.post(f"/api/v1/jobs/{job['id']}/proceed")
    resp = client.post(f"/api/v1/jobs/{job['id']}/tailor")
    assert resp.status_code == 409
    assert "Word" in resp.json()["detail"]


def test_tailoring_reorders_a_copy_and_leaves_the_master_untouched(app_and_db, monkeypatch, docs_dir):
    client, _ = app_and_db
    client.post("/api/v1/profile/commit", json=_PROFILE)
    job = _add_job(client, monkeypatch)
    client.post(f"/api/v1/jobs/{job['id']}/proceed")
    master_before = _write_master(docs_dir)

    _FakePlanRouter.plan = _plan([2, 0, 1], changelog=["Gap: the job wants Kubernetes; not in your resume."])
    monkeypatch.setattr("app.services.resume.generation.ModelRouter", _FakePlanRouter)

    resp = client.post(f"/api/v1/jobs/{job['id']}/tailor")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["used_original_wording"] is False
    assert body["changelog"] == ["Gap: the job wants Kubernetes; not in your resume."]
    assert sorted(d["document_type"] for d in body["documents"]) == ["changelog", "resume"]

    resume_doc = next(d for d in body["documents"] if d["document_type"] == "resume")
    download = client.get(f"/api/v1/jobs/documents/{resume_doc['id']}/download")
    assert download.status_code == 200
    # The header is percent-encoded (spaces become %20); browsers decode it back.
    assert "Jane Doe_Resume_Globex_" in unquote(download.headers["content-disposition"])
    assert _docx_bullets(download.content) == [_BULLETS[2], _BULLETS[0], _BULLETS[1]]
    heading_line = Document(io.BytesIO(download.content)).paragraphs[1].text
    assert "\u2013" not in heading_line and "2020 - Present" in heading_line  # en dash became a hyphen

    assert (docs_dir / "master_resume" / "master.docx").read_bytes() == master_before

    listed = client.get("/api/v1/jobs").json()[0]
    assert sorted(d["document_type"] for d in listed["documents"]) == ["changelog", "resume"]


def test_tailoring_falls_back_to_the_master_when_the_ai_plan_fails_checks(app_and_db, monkeypatch, docs_dir):
    client, _ = app_and_db
    client.post("/api/v1/profile/commit", json=_PROFILE)
    job = _add_job(client, monkeypatch)
    client.post(f"/api/v1/jobs/{job['id']}/proceed")
    _write_master(docs_dir)

    _FakePlanRouter.plan = _plan([0, 1])  # drops a bullet: must be rejected
    monkeypatch.setattr("app.services.resume.generation.ModelRouter", _FakePlanRouter)

    resp = client.post(f"/api/v1/jobs/{job['id']}/tailor")
    assert resp.status_code == 200
    body = resp.json()
    assert body["used_original_wording"] is True
    assert any("accuracy checks" in note for note in body["changelog"])

    resume_doc = next(d for d in body["documents"] if d["document_type"] == "resume")
    download = client.get(f"/api/v1/jobs/documents/{resume_doc['id']}/download")
    assert _docx_bullets(download.content) == _BULLETS


def test_recreating_a_tailored_resume_replaces_the_old_one(app_and_db, monkeypatch, docs_dir):
    client, _ = app_and_db
    client.post("/api/v1/profile/commit", json=_PROFILE)
    job = _add_job(client, monkeypatch)
    client.post(f"/api/v1/jobs/{job['id']}/proceed")
    _write_master(docs_dir)
    _FakePlanRouter.plan = _plan([1, 0, 2])
    monkeypatch.setattr("app.services.resume.generation.ModelRouter", _FakePlanRouter)

    client.post(f"/api/v1/jobs/{job['id']}/tailor")
    second = client.post(f"/api/v1/jobs/{job['id']}/tailor").json()

    resume_doc = next(d for d in second["documents"] if d["document_type"] == "resume")
    download = client.get(f"/api/v1/jobs/documents/{resume_doc['id']}/download")
    assert download.status_code == 200  # the new file still exists after the old one was cleared
    assert len(client.get("/api/v1/jobs").json()[0]["documents"]) == 2


def test_download_refuses_unknown_and_out_of_folder_documents(app_and_db, monkeypatch, docs_dir):
    client, SessionLocal = app_and_db
    job = _add_job(client, monkeypatch)
    secret = docs_dir / "secret.txt"
    secret.write_text("private")
    with SessionLocal() as db:
        doc = GeneratedDocument(
            job_id=job["id"],
            document_type="resume",
            local_path=str(secret),
            format="txt",
            generated_at=dt.datetime.now(dt.timezone.utc),
            template_version="t",
            source_claim_ids=[],
            content_hash="h",
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id

    assert client.get(f"/api/v1/jobs/documents/{doc_id}/download").status_code == 404
    assert client.get("/api/v1/jobs/documents/9999/download").status_code == 404


# --- work eligibility answers -------------------------------------------------


def test_work_eligibility_answers_need_a_profile_then_round_trip(app_and_db):
    client, _ = app_and_db
    assert client.get("/api/v1/profile/answers").status_code == 404

    client.post("/api/v1/profile/commit", json=_PROFILE)
    saves = {
        "work_authorization": {"value_type": "str", "value": "US citizen"},
        "sponsorship_required": {"value_type": "bool", "value": False},
        "security_clearance": {"value_type": "str", "value": "None"},
    }
    for key, payload in saves.items():
        assert client.put(f"/api/v1/profile/answers/{key}", json=payload).status_code == 200

    answers = {a["answer_key"]: a["value"] for a in client.get("/api/v1/profile/answers").json()}
    assert answers == {
        "work_authorization": "US citizen",
        "sponsorship_required": False,
        "security_clearance": "None",
    }

    client.put(
        "/api/v1/profile/answers/sponsorship_required", json={"value_type": "bool", "value": True}
    )
    updated = {a["answer_key"]: a["value"] for a in client.get("/api/v1/profile/answers").json()}
    assert updated["sponsorship_required"] is True
    assert len(client.get("/api/v1/profile/answers").json()) == 3  # updated in place, not duplicated


def test_original_resume_needs_proceed_first(app_and_db, monkeypatch, docs_dir):
    client, _ = app_and_db
    job = _add_job(client, monkeypatch)
    assert client.post(f"/api/v1/jobs/{job['id']}/original-resume").status_code == 409


def test_original_resume_without_a_master_explains_what_to_do(app_and_db, monkeypatch, docs_dir):
    client, _ = app_and_db
    client.post("/api/v1/profile/commit", json=_PROFILE)
    job = _add_job(client, monkeypatch)
    client.post(f"/api/v1/jobs/{job['id']}/proceed")
    resp = client.post(f"/api/v1/jobs/{job['id']}/original-resume")
    assert resp.status_code == 409 and "Upload your resume" in resp.json()["detail"]


def test_original_resume_is_an_unchanged_copy_and_the_master_is_untouched(app_and_db, monkeypatch, docs_dir):
    client, _ = app_and_db
    client.post("/api/v1/profile/commit", json=_PROFILE)
    job = _add_job(client, monkeypatch)
    client.post(f"/api/v1/jobs/{job['id']}/proceed")
    master_before = _write_master(docs_dir)

    resp = client.post(f"/api/v1/jobs/{job['id']}/original-resume")
    assert resp.status_code == 200, resp.text
    docs = resp.json()
    assert [d["document_type"] for d in docs] == ["resume"] and docs[0]["template_version"] == "original-1"
    download = client.get(f"/api/v1/jobs/documents/{docs[0]['id']}/download")
    assert "Jane Doe_Resume_Globex_" in unquote(download.headers["content-disposition"])
    assert download.content == master_before
    assert (docs_dir / "master_resume" / "master.docx").read_bytes() == master_before

    listed = client.get("/api/v1/jobs").json()[0]
    assert [d["document_type"] for d in listed["documents"]] == ["resume"]


def test_mark_applied_with_a_date_and_take_it_back(app_and_db, monkeypatch):
    client, _ = app_and_db
    job = _add_job(client, monkeypatch)
    assert job["applied_at"] is None
    out = client.post(f"/api/v1/jobs/{job['id']}/applied", json={"applied_on": "2026-10-01"}).json()
    assert out["applied_at"].startswith("2026-10-01") and out["applied_via"] == "manual"
    out = client.post(f"/api/v1/jobs/{job['id']}/applied").json()  # no date: today
    assert out["applied_at"] is not None
    assert client.post(f"/api/v1/jobs/{job['id']}/applied", json={"applied_on": "2999-01-01"}).status_code == 422
    out = client.post(f"/api/v1/jobs/{job['id']}/unapplied").json()
    assert out["applied_at"] is None and out["applied_via"] is None
    assert client.post("/api/v1/jobs/9999/applied").status_code == 404


class _FakeDraftRouter:
    def __init__(self, db):
        pass

    async def get_structured(self, **kwargs):
        from app.services.followup.draft import FollowUpDraft

        user = kwargs["messages"][-1]["content"]
        return FollowUpDraft(subject="Checking in — Data Analyst", body=f"Hello, {user[:20]} – thanks.")


def test_follow_up_draft_is_returned_not_saved_and_has_no_long_dashes(app_and_db, monkeypatch):
    client, _ = app_and_db
    job = _add_job(client, monkeypatch)
    monkeypatch.setattr("app.services.followup.draft.ModelRouter", _FakeDraftRouter)
    resp = client.post(f"/api/v1/jobs/{job['id']}/follow-up-draft", json={"kind": "after_interview"})
    assert resp.status_code == 200
    out = resp.json()
    assert out["subject"] == "Checking in , Data Analyst"
    assert "—" not in out["body"] and "–" not in out["body"]
    assert client.post(f"/api/v1/jobs/{job['id']}/follow-up-draft").status_code == 200  # kind is optional
    assert client.post("/api/v1/jobs/9999/follow-up-draft").status_code == 404


def test_follow_up_draft_without_an_llm_is_a_clear_error(app_and_db, monkeypatch):
    client, _ = app_and_db
    job = _add_job(client, monkeypatch)
    assert client.post(f"/api/v1/jobs/{job['id']}/follow-up-draft").status_code == 502
