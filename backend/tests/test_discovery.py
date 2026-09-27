"""
Milestone 3 acceptance coverage: search profiles, the employer watchlist,
and a discovery run — end to end through the API, with the Greenhouse/Lever
providers replaced by a fake so tests never hit the real network (matching
the same "no live network calls in tests" approach as test_profile.py's LLM
handling).
"""

from __future__ import annotations

from app.services.discovery.base import RawJobPosting
from app.services.discovery import pipeline as pipeline_module


class _FakeProvider:
    """Stands in for GreenhouseProvider/LeverProvider in tests."""

    def __init__(self, postings: list[RawJobPosting]):
        self._postings = postings

    def search(self, identifier: str) -> list[RawJobPosting]:
        return self._postings

    def health_check(self, identifier: str) -> bool:
        return True


def _install_fake_provider(monkeypatch, postings: list[RawJobPosting]) -> None:
    monkeypatch.setitem(pipeline_module.PROVIDERS, "greenhouse", _FakeProvider(postings))


def test_search_profile_crud(app_and_db):
    client, _ = app_and_db

    create_resp = client.post(
        "/api/v1/search-profiles",
        json={"name": "Data roles", "titles": ["Data Analyst"], "locations": ["Boston"]},
    )
    assert create_resp.status_code == 201
    profile_id = create_resp.json()["id"]

    list_resp = client.get("/api/v1/search-profiles")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    patch_resp = client.patch(f"/api/v1/search-profiles/{profile_id}", json={"enabled": False})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["enabled"] is False

    delete_resp = client.delete(f"/api/v1/search-profiles/{profile_id}")
    assert delete_resp.status_code == 204
    assert client.get("/api/v1/search-profiles").json() == []


def test_target_employer_crud_rejects_unsupported_ats(app_and_db):
    client, _ = app_and_db

    bad_resp = client.post(
        "/api/v1/discovery/employers",
        json={"name": "Acme", "ats": "workday", "identifier": "acme"},
    )
    assert bad_resp.status_code == 400

    good_resp = client.post(
        "/api/v1/discovery/employers",
        json={"name": "Acme", "ats": "greenhouse", "identifier": "acme"},
    )
    assert good_resp.status_code == 201
    assert client.get("/api/v1/discovery/employers").json()[0]["identifier"] == "acme"


def test_discovery_run_with_no_search_profiles_fetches_nothing(app_and_db):
    client, _ = app_and_db
    client.post("/api/v1/discovery/employers", json={"name": "Acme", "ats": "greenhouse", "identifier": "acme"})

    run_resp = client.post("/api/v1/discovery/run")
    assert run_resp.status_code == 200
    body = run_resp.json()
    assert body["employers_checked"] == 0
    assert any("No enabled search profile" in e for e in body["errors"])


def test_discovery_run_matches_and_dedupes(app_and_db, monkeypatch):
    client, _ = app_and_db

    client.post(
        "/api/v1/search-profiles",
        json={"name": "Data roles", "titles": ["Data Analyst"], "remote": True, "hybrid": True, "onsite": False},
    )
    client.post("/api/v1/discovery/employers", json={"name": "Acme", "ats": "greenhouse", "identifier": "acme"})

    postings = [
        RawJobPosting(
            external_job_id="1",
            title="Senior Data Analyst",
            company="Acme",
            location="Remote - US",
            description_html="<p>Must know SQL</p>",
            application_url="https://boards.greenhouse.io/acme/jobs/1?gh_src=track",
        ),
        RawJobPosting(
            external_job_id="2",
            title="Warehouse Associate",  # shouldn't match the "Data Analyst" search profile
            company="Acme",
            location="Boston, MA (On-site)",
            description_html="<p>Lift boxes</p>",
            application_url="https://boards.greenhouse.io/acme/jobs/2",
        ),
    ]
    _install_fake_provider(monkeypatch, postings)

    run_resp = client.post("/api/v1/discovery/run")
    assert run_resp.status_code == 200
    body = run_resp.json()
    assert body["employers_checked"] == 1
    assert body["postings_fetched"] == 2
    assert body["postings_matched"] == 1  # only the Data Analyst posting
    assert body["jobs_created"] == 1

    jobs_resp = client.get("/api/v1/jobs")
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Senior Data Analyst"
    assert jobs[0]["remote_type"] == "remote"
    assert "gh_src" not in jobs[0]["canonical_application_url"]

    # Running discovery again with the same posting updates rather than duplicates.
    run_resp_2 = client.post("/api/v1/discovery/run")
    assert run_resp_2.json()["jobs_created"] == 0
    assert run_resp_2.json()["jobs_updated"] == 1
    assert len(client.get("/api/v1/jobs").json()) == 1

    job_id = jobs[0]["id"]
    detail_resp = client.get(f"/api/v1/jobs/{job_id}")
    assert detail_resp.status_code == 200
    assert "SQL" in detail_resp.json()["description"]
