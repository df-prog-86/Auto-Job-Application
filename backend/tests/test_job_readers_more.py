"""Readers for Breezy, Workable, BambooHR, Pinpoint, JazzHR, Jobvite and Oracle Cloud. Breezy, Oracle and Pinpoint shapes come from real answers."""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from app.services.jobcache import readers
from app.services.jobcache.store import guess_name, known_name


@pytest.mark.parametrize(
    "url,ref",
    [
        ("https://tyton-partners.breezy.hr/p/8c3d67b30931-senior-associate", ("breezy", "tyton-partners")),
        ("https://tyton-partners.breezy.hr/json", ("breezy", "tyton-partners")),
        ("https://www.breezy.hr/pricing", None),
        ("https://apply.workable.com/rapdev/", ("workable", "rapdev")),
        ("https://apply.workable.com/j/ABC123", None),
        ("https://reptrak.bamboohr.com/careers/12", ("bamboohr", "reptrak")),
        ("https://igsinsights.pinpointhq.com/en/postings/548390", ("pinpoint", "igsinsights")),
        ("https://kaufmanhall.applytojob.com/apply", ("jazzhr", "kaufmanhall")),
        ("https://jobs.jobvite.com/medullan/jobs", ("jobvite", "medullan")),
        ("https://jobs.jobvite.com/careers", None),
        ("https://ebez.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs", ("oracle", "ebez.fa.us2.oraclecloud.com|CX_1")),
        ("https://eedu.fa.em3.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1003/job/9", ("oracle", "eedu.fa.em3.oraclecloud.com|CX_1003")),
        ("https://ebez.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/", None),
        ("https://example.com/careers", None),
    ],
)
def test_links_are_recognised(url, ref):
    assert readers.employer_ref(url) == ref


def test_breezy_postings_are_parsed():
    data = [
        {"id": "8c3d", "friendly_id": "8c3d-senior-associate", "name": "Senior Associate, Strategy Consulting Practice",
         "url": "https://tyton-partners.breezy.hr/p/8c3d-senior-associate", "published_date": "2026-09-21T15:31:52.944Z",
         "location": {"name": "Boston, MA", "is_remote": True}, "salary": "$120,000 / year"},
        {"id": "c8a7", "name": "Contractor Pipeline", "url": "https://tyton-partners.breezy.hr/p/c8a7", "published_date": "2025-08-18T20:12:35.240Z",
         "location": {"name": "United States", "is_remote": False}, "salary": ""},
        {"id": None, "name": "No id"},
    ]
    a, b = readers.parse_breezy(data, "tyton-partners")
    assert a.title.startswith("Senior Associate") and a.location == "Boston, MA" and a.work_type == "remote"
    assert a.pay_text == "$120,000 / year" and a.pay_mid == 120000 and a.posted_at == dt.date(2026, 9, 21)
    assert b.pay_text is None and b.work_type is None


def test_oracle_postings_are_parsed_and_the_total_is_read():
    data = {"items": [{"TotalJobsCount": 231, "SiteNumber": "CX_1", "requisitionList": [
        {"Id": "6606", "Title": "Field Service Technician | Network Solutions", "PostedDate": "2026-10-09", "PrimaryLocation": "Watertown, SD, United States", "WorkplaceType": "Hybrid"},
        {"Id": "6608", "Title": "Receptionist", "PostedDate": "2026-10-09", "PrimaryLocation": "New York, NY, United States", "WorkplaceType": "On-site"},
    ]}]}
    posts, total = readers.parse_oracle(data, "ebez.fa.us2.oraclecloud.com", "CX_1")
    assert total == 231 and len(posts) == 2
    assert posts[0].location == "Watertown, SD" and posts[0].work_type == "hybrid" and posts[1].work_type == "onsite"
    assert posts[0].url == "https://ebez.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/6606"
    assert posts[0].posted_at == dt.date(2026, 10, 9)


class _Resp:
    status_code = 200
    headers: dict = {}

    def __init__(self, body, text=None):
        self._body, self.text = body, text

    def json(self):
        return self._body


class _NoWait:
    async def wait(self, host, gap):
        return None


def test_oracle_reader_pages_until_the_total_is_reached():
    urls = []

    class Client:
        async def request(self, method, url, **kw):
            urls.append(url)
            off = int(url.split("offset=")[1].split(",")[0])
            n = 100 if off < 200 else 31
            return _Resp({"items": [{"TotalJobsCount": 231, "requisitionList": [{"Id": str(off + i), "Title": f"Job {off + i}"} for i in range(n)]}]})

    res = asyncio.run(readers.read_employer("oracle", "ebez.fa.us2.oraclecloud.com|CX_1", Client(), _NoWait()))
    assert len(res.postings) == 231 and res.complete and len(urls) == 3
    assert "finder=findReqs;siteNumber=CX_1,limit=100,offset=0" in urls[0]


def test_oracle_reader_refuses_an_answer_it_does_not_understand():
    class Client:
        async def request(self, method, url, **kw):
            return _Resp({"oops": 1})

    with pytest.raises(readers.ReaderError):
        asyncio.run(readers.read_employer("oracle", "x.fa.us2.oraclecloud.com|CX_1", Client(), _NoWait()))


def test_workable_bamboohr_and_pinpoint_are_parsed():
    w = readers.parse_workable({"name": "Acme", "jobs": [{"title": "Analyst", "shortcode": "AB12", "url": "https://apply.workable.com/j/AB12", "city": "Boston", "state": "Massachusetts", "country": "United States", "telecommuting": False, "published_on": "2026-10-01"}]}, "acme")
    assert w[0].ext_id == "AB12" and w[0].location == "Boston, Massachusetts" and w[0].posted_at == dt.date(2026, 10, 1)
    assert readers.parse_workable({"name": "RapDev.io", "jobs": []}, "rapdev") == []
    b = readers.parse_bamboohr({"meta": {"totalCount": 1}, "result": [{"id": "7", "jobOpeningName": "Coder", "location": {"city": "Austin", "state": "Texas"}, "isRemote": None}]}, "reptrak")
    assert b[0].url == "https://reptrak.bamboohr.com/careers/7" and b[0].location == "Austin, Texas"
    assert readers.parse_bamboohr({"meta": {"totalCount": 0}, "result": []}, "reptrak") == []
    p = readers.parse_pinpoint({"data": [{"id": "548390", "title": "Associate", "url": "https://igsinsights.pinpointhq.com/en/postings/548390", "compensation": "$100,000 - $108,000 / year",
                                          "compensation_minimum": 100000.0, "compensation_maximum": 108000.0, "compensation_frequency": "year", "compensation_visible": True,
                                          "location": {"name": "Boston, MA"}, "workplace_type": "hybrid"}]}, "igsinsights")
    assert p[0].pay_mid == 104000 and p[0].location == "Boston, MA" and p[0].work_type == "hybrid"


def test_jazzhr_and_jobvite_pages_are_parsed():
    jazz = (
        '<ul><li class="list-group-item"><h4 class="list-group-item-heading"><a href="https://acme.applytojob.com/apply/AbCdEf12/Senior-Analyst?source=x">Senior Analyst</a></h4>'
        '<ul class="list-inline list-group-item-text"><li><i class="fa fa-map-marker"></i> Boston, MA</li></ul></li></ul>'
    )
    j = readers.parse_jazzhr(jazz, "acme")
    assert len(j) == 1 and j[0].ext_id == "AbCdEf12" and j[0].location == "Boston, MA" and "?" not in j[0].url
    jv = '<table><tr><td class="jv-job-list-name"><a href="/medullan/job/oXyZ123">Data Engineer</a></td><td class="jv-job-list-location"> Boston, MA </td></tr></table>'
    r = readers.parse_jobvite(jv, "medullan")
    assert len(r) == 1 and r[0].url == "https://jobs.jobvite.com/medullan/job/oXyZ123" and r[0].location == "Boston, MA"


def test_a_page_with_no_jobs_and_no_explanation_is_an_error_not_an_empty_list():
    class Client:
        def __init__(self, text):
            self.text = text

        async def request(self, method, url, **kw):
            return _Resp(None, self.text)

    with pytest.raises(readers.ReaderError):
        asyncio.run(readers.read_employer("jazzhr", "acme", Client("<html><body><div>new layout</div></body></html>"), _NoWait()))
    ok = asyncio.run(readers.read_employer("jobvite", "acme", Client("<html><body>There are no open positions right now.</body></html>"), _NoWait()))
    assert ok.postings == []


def test_known_names_for_the_new_systems():
    assert known_name("oracle", "ehzq.fa.us2.oraclecloud.com|CX_1") == "Grant Thornton"
    assert known_name("pinpoint", "igsinsights") == "IGS"
    assert guess_name("oracle", "zzzz.fa.us2.oraclecloud.com|CX_1") == "Zzzz"
    assert guess_name("breezy", "some-firm") == "Some Firm"
