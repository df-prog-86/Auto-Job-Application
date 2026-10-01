"""Greenhouse job-board pages: title/company come from the tab title, no LLM needed."""

from __future__ import annotations

from app.services.discovery.manual_extraction import extract_from_greenhouse_page

URL = "https://job-boards.greenhouse.io/kodiaksolutions/jobs/4163219009"
TITLE = "Job Application for Clinical Revenue Cycle Sr Associate at Kodiak Solutions"
BODY = "Clinical Revenue Cycle Sr Associate\nRemote\nApply\nAbout the role..."


def test_greenhouse_title_parsed():
    p = extract_from_greenhouse_page(URL + "?gh_src=x", TITLE, BODY)
    assert p is not None
    assert p.title == "Clinical Revenue Cycle Sr Associate"
    assert p.company == "Kodiak Solutions"
    assert p.external_job_id == "4163219009"
    assert p.location == "Remote"
    assert p.application_url == URL


def test_non_greenhouse_or_odd_title_returns_none():
    assert extract_from_greenhouse_page("https://example.com/jobs/1", TITLE, BODY) is None
    assert extract_from_greenhouse_page(URL, "Careers home", BODY) is None
    assert extract_from_greenhouse_page(URL, None, BODY) is None
    assert extract_from_greenhouse_page("https://job-boards.greenhouse.io/acme", TITLE, BODY) is None


def test_capture_endpoint_without_llm(app_and_db):
    client, _ = app_and_db
    secret = client.post("/api/v1/system/pairing-secret").json()["pairing_secret"]
    token = client.post(
        "/api/v1/system/pair", json={"pairing_secret": secret, "extension_origin": "chrome-extension://t"}
    ).json()["extension_token"]
    r = client.post(
        "/api/v1/jobs/capture",
        json={"url": URL, "json_ld": [], "body_text": BODY, "page_title": TITLE},
        headers={"X-Extension-Token": token},
    )
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "Clinical Revenue Cycle Sr Associate"
    assert r.json()["company"] == "Kodiak Solutions"
