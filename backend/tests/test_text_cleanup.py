from __future__ import annotations

import pytest

from app.services.discovery.web_search import tidy_items
from app.services.jobcache.text import clean_company, clean_title, decode_text, reconcile_place


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("Johnson &amp; Johnson", "Johnson & Johnson"),
        ("Nurse &amp;amp; Aide", "Nurse & Aide"),
        ("  Plain   title ", "Plain title"),
        ("Ben &amp; Jerry&#39;s", "Ben & Jerry's"),
        (None, ""),
    ],
)
def test_decode_text(raw, want):
    assert decode_text(raw) == want


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("9998 Ochsner Health", "Ochsner Health"),
        ("1000 Abbott Laboratories Inc(ALI)", "Abbott Laboratories Inc"),
        ("109 Trellix", "Trellix"),
        ("LE001 Berkeley Research Group", "Berkeley Research Group"),
        ("Mmc", "Marsh McLennan"),
        ("Msk", "Memorial Sloan Kettering Cancer Center"),
        ("Fticonsulting", "FTI Consulting"),
        ("Johnson &amp; Johnson", "Johnson & Johnson"),
        ("Acme", "Acme"),
    ],
)
def test_clean_company(raw, want):
    assert clean_company(raw) == want


def test_clean_title_decodes_and_drops_at_employer():
    assert clean_title("Analyst &amp; Planner at Acme", "Acme") == "Analyst & Planner"


@pytest.mark.parametrize(
    ("loc", "wt", "want"),
    [
        ("USA-NC-Virtual", "hybrid", ("Remote (NC)", "remote")),
        ("Location not listed", "remote", ("Remote", "remote")),
        ("Boston, MA", "hybrid", ("Boston, MA", "hybrid")),
        ("Boston, MA (Hybrid, remote Fridays)", "hybrid", ("Boston, MA (Hybrid, remote Fridays)", "hybrid")),
        ("Remote (US)", "remote", ("Remote (US)", "remote")),
        (None, None, (None, None)),
        ("Location not listed", None, (None, None)),
    ],
)
def test_reconcile_place(loc, wt, want):
    assert reconcile_place(loc, wt) == want


def test_tidy_items_applies_everything():
    items = [{"title": "R&amp;D Analyst", "company": "9998 Ochsner &amp; Co", "location": "USA-NC-Virtual", "work_type": "hybrid"}]
    tidy_items(items)
    assert items[0]["title"] == "R&D Analyst"
    assert items[0]["company"] == "Ochsner & Co"
    assert (items[0]["location"], items[0]["work_type"]) == ("Remote (NC)", "remote")


def test_tidy_jobs_script_dry_run_then_apply(app_and_db):
    import datetime as dt

    from app.models.jobs import Job
    from scripts.tidy_jobs import duplicate_groups, tidy_jobs

    _client, Session = app_and_db
    now = dt.datetime.now(dt.UTC)

    def make(i, company, title, location, remote):
        return Job(
            canonical_job_key=f"k{i}", company=company, normalized_company=company.lower(), title=title,
            normalized_title=title.lower(), location=location, remote_type=remote, salary={},
            canonical_application_url="https://x.test/%d" % i, first_seen=now, last_seen=now,
        )

    with Session() as db:
        db.add_all([
            make(1, "9998 Ochsner &amp; Co", "Analyst &amp; Planner", "USA-NC-Virtual", "hybrid"),
            make(2, "Ochsner & Co", "Analyst & Planner", "USA-NC-Virtual", "remote"),
            make(3, "Clean Inc", "Fine Title", "Boston, MA", "onsite"),
        ])
        db.commit()
        planned = tidy_jobs(db, apply=False)
        assert [pid for pid, _ in planned] == [1, 2] or [pid for pid, _ in planned] == [1]
        assert db.get(Job, 1).company == "9998 Ochsner &amp; Co"  # a dry run changes nothing
        tidy_jobs(db, apply=True)
        db.expire_all()
        one = db.get(Job, 1)
        assert (one.company, one.title, one.location, one.remote_type) == ("Ochsner & Co", "Analyst & Planner", "Remote (NC)", "remote")
        assert db.get(Job, 3).company == "Clean Inc"
        groups = duplicate_groups(db)
        assert len(groups) == 1 and {j.id for j in groups[0]} == {1, 2}


def test_places_are_shown_plainly():
    from app.services.jobcache.text import display_place

    assert display_place("USA-NC-Virtual", "hybrid") == ("Remote (NC)", "remote")
    assert display_place("Location not listed", "remote") == ("Remote", "remote")
    assert display_place("Remote: United States", None) == ("Remote (US)", "remote")
    assert display_place("Working Virtually", None) == ("Remote", "remote")
    assert display_place("USA NY New York City 3 Times Square 7th Floor", "onsite") == ("New York City, NY", "onsite")
    assert display_place("BRG-Chicago IL", None)[0] == "Chicago, IL"
    assert display_place("NJ-Jersey City", None)[0] == "Jersey City, NJ"
    assert display_place("Boston MA", None)[0] == "Boston, MA"
    assert display_place("Client Site - USA - NY - New York - 11 Madison Avenue", None)[0] == "New York, NY"
    assert display_place("New York, NY; Atlanta, GA; Roseland, NJ; Dallas, TX; Austin, TX", None)[0] == "New York, NY +4 more"
    assert display_place("Remote, USA", "remote") == ("Remote, USA", "remote")
