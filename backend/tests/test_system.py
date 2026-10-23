"""
Milestone 1 acceptance surface: health/version, and the full pairing flow
(pairing-secret -> pair -> extension-token accepted on a protected route).
"""

from __future__ import annotations


def test_health(app_and_db):
    client, _ = app_and_db
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_version(app_and_db):
    client, _ = app_and_db
    resp = client.get("/api/v1/version")
    body = resp.json()
    assert resp.status_code == 200
    assert body["api_version"] == "1"


def test_automation_start_pause_roundtrip(app_and_db):
    client, _ = app_and_db
    assert client.get("/api/v1/automation/status").json()["mode"] == "PAUSED"

    started = client.post("/api/v1/automation/start")
    assert started.json()["mode"] == "REVIEW"
    assert client.get("/api/v1/automation/status").json()["mode"] == "REVIEW"

    paused = client.post("/api/v1/automation/pause")
    assert paused.json()["mode"] == "PAUSED"


def test_pairing_flow(app_and_db):
    client, _ = app_and_db

    secret_resp = client.post("/api/v1/system/pairing-secret")
    assert secret_resp.status_code == 200
    secret = secret_resp.json()["pairing_secret"]
    assert len(secret) > 20

    pair_resp = client.post(
        "/api/v1/system/pair",
        json={"pairing_secret": secret, "extension_origin": "chrome-extension://test"},
    )
    assert pair_resp.status_code == 200
    token = pair_resp.json()["extension_token"]
    assert len(token) > 20

    # Secret is single-use.
    reuse_resp = client.post(
        "/api/v1/system/pair",
        json={"pairing_secret": secret, "extension_origin": "chrome-extension://test"},
    )
    assert reuse_resp.status_code == 403


def test_pairing_wrong_secret_rejected(app_and_db):
    client, _ = app_and_db
    client.post("/api/v1/system/pairing-secret")
    resp = client.post(
        "/api/v1/system/pair",
        json={"pairing_secret": "not-the-real-secret", "extension_origin": "x"},
    )
    assert resp.status_code == 403


def test_pairing_status_before_and_after_pairing(app_and_db):
    client, _ = app_and_db
    before = client.get("/api/v1/system/pairing-status").json()
    assert before["paired"] is False and before["paired_at"] is None

    secret = client.post("/api/v1/system/pairing-secret").json()["pairing_secret"]
    client.post("/api/v1/system/pair", json={"pairing_secret": secret, "extension_origin": "chrome-extension://test"})
    after = client.get("/api/v1/system/pairing-status").json()
    assert after["paired"] is True and after["paired_at"]
    assert "token" not in " ".join(after.keys())


def test_master_resume_remembers_original_file_name(tmp_path, monkeypatch):
    from app.services.resume import master

    monkeypatch.setattr(master, "master_dir", lambda: tmp_path)
    master.save_master(b"x", "C:\\Users\\me\\Dylan_Faires_Resume.docx")
    assert master.master_status()["filename"] == "Dylan_Faires_Resume.docx"
    master.save_master(b"y", None)
    assert master.master_status()["filename"] is None
    assert master.master_status()["saved"] is True
