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
    assert a.title.startswith("Senior Associate") and a.location == "Boston, MA" and a.work_type is None  # a remote flag on a job with a city does not make it remote
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


ICIMS_PAGE = (
    '<div>Page 1 of 2</div><ul><li class="iCIMS_JobCardItem"> <div class="row"> <div class="col-xs-6 header left"> <span class="sr-only field-label">Job Locations</span> <span > US-MA-Waltham</span> </div>'
    ' <div class="col-xs-12 title"> <a href="https://careers-berrydunn.icims.com/jobs/4103/staff-auditor/job?in_iframe=1" class="iCIMS_Anchor" title="4103 - Staff Auditor">'
    ' <span class="sr-only field-label">Title</span> <h3 > Staff Auditor</h3> </a> </div> <div class="col-xs-12 description">Are you curious...</div></div></li>'
    '<li class="iCIMS_JobCardItem"> <div class="row"> <div class="col-xs-6 header left"> <span class="sr-only field-label">Job Locations</span> <span > US-Remote</span> </div>'
    ' <div class="col-xs-12 title"> <a href="https://careers-berrydunn.icims.com/jobs/4085/medicaid-h.r.-1-project-manager/job?in_iframe=1" title="4085 - Medicaid-H.R.1 Project Manager">'
    ' <h3 > Medicaid-H.R.1 Project Manager</h3> </a> </div></div></li></ul>'
)


def test_icims_links_and_places():
    assert readers.employer_ref("https://careers-cotiviti.icims.com/jobs/20126/data-governance/job") == ("icims", "careers-cotiviti.icims.com")
    assert readers.employer_ref("https://www.icims.com/") is None
    assert readers._icims_place("US-MA-Waltham") == "Waltham, MA"
    assert readers._icims_place("US-Remote") == "Remote"
    assert readers._icims_place("GB-London") == "London"
    assert readers._icims_place("US-MA-Boston | US-NY-New York") == "Boston, MA; New York, NY"


def test_icims_cards_are_parsed():
    posts, pages = readers.parse_icims(ICIMS_PAGE, "careers-berrydunn.icims.com")
    assert pages == 2 and len(posts) == 2
    assert posts[0].ext_id == "4103" and posts[0].title == "Staff Auditor" and posts[0].location == "Waltham, MA"
    assert posts[0].url == "https://careers-berrydunn.icims.com/jobs/4103/staff-auditor/job"
    assert posts[1].work_type == "remote" and posts[1].title.startswith("Medicaid")


def test_icims_reader_follows_the_pages_and_refuses_a_page_it_cannot_read():
    seen = []

    class Client:
        def __init__(self, texts):
            self.texts = texts

        async def request(self, method, url, **kw):
            seen.append(url)
            self.n = getattr(self, "n", 0) + 1
            return _Resp(None, self.texts[self.n - 1])

    page2 = ICIMS_PAGE.replace("4103", "5103").replace("4085", "5085").replace("Page 1 of 2", "Page 2 of 2")
    res = asyncio.run(readers.read_employer("icims", "careers-berrydunn.icims.com", Client([ICIMS_PAGE, page2]), _NoWait()))
    assert len(res.postings) == 4 and res.complete and seen[1].endswith("pr=1")
    with pytest.raises(readers.ReaderError):
        asyncio.run(readers.read_employer("icims", "x.icims.com", Client(["<html>new layout</html>"]), _NoWait()))
    assert guess_name("icims", "careers-cotiviti.icims.com") == "Cotiviti"
    assert guess_name("icims", "careers-berrydunn.icims.com") == "BerryDunn"


def test_workday_reads_a_list_longer_than_the_old_limit_in_full():
    class Client:
        async def request(self, method, url, **kw):
            off = kw["json"]["offset"]
            n = max(0, min(20, 2300 - off))
            return _Resp({"total": 2300, "jobPostings": [{"title": f"Job {off + i}", "externalPath": f"/job/x/{off + i}", "locationsText": "Boston, MA"} for i in range(n)]})

    res = asyncio.run(readers.read_employer("workday", "big.wd1.myworkdayjobs.com|big|Careers", Client(), _NoWait()))
    assert len(res.postings) == 2300 and res.complete


TALEO_PAGE = (
    '<div class="oracletaleocwsv2-accordion-head-info"> <h4 class="oracletaleocwsv2-head-title"><a href="https://phh.tbe.taleo.net/phh01/ats/careers/v2/viewRequisition?org=THEBRIDG12&cws=40&rid=530" class="viewJobLink">'
    'Experienced Associate Consultant BOS/DC - Q3 2026 or Q1 2027 Start Date</a></h4> <div tabindex="0" >Boston or Washington D.C.</div> </div>'
    '<div class="oracletaleocwsv2-accordion-head-info"> <h4 class="oracletaleocwsv2-head-title"><a href="https://phh.tbe.taleo.net/phh01/ats/careers/v2/viewRequisition?org=THEBRIDG12&cws=40&rid=536" class="viewJobLink">'
    'Office Operations Manager</a></h4> <div tabindex="0" >Boston</div> </div>'
)


def test_taleo_links_and_page():
    assert readers.employer_ref("https://phh.tbe.taleo.net/phh01/ats/careers/v2/searchResults?org=THEBRIDG12&cws=40") == ("taleo", "phh.tbe.taleo.net|phh01|THEBRIDG12|40")
    assert readers.employer_ref("https://phh.tbe.taleo.net/phh01/ats/careers/v2/viewRequisition?org=THEBRIDG12&cws=40&rid=530") == ("taleo", "phh.tbe.taleo.net|phh01|THEBRIDG12|40")
    assert readers.employer_ref("https://phh.tbe.taleo.net/phh01/") is None
    a, b = readers.parse_taleo(TALEO_PAGE)
    assert a.ext_id == "530" and a.location == "Boston or Washington D.C." and "rid=530" in a.url and b.title == "Office Operations Manager"
    assert known_name("taleo", "phh.tbe.taleo.net|phh01|THEBRIDG12|40") == "The Bridgespan Group"


def test_phenom_answer_is_parsed_and_paged():
    job = {"title": "Global Cybersecurity Senior Manager", "jobId": "60176", "location": "Gurgaon, Haryana, India", "postedDate": "2026-10-12T00:00:00.000+0000",
           "applyUrl": "https://experiencedtalent.bcg.com/careerhub/explore/jobs/790318893600?post_onboarding_pid=790318893600&amp;show_apply=1"}
    posts, total = readers.parse_phenom({"refineSearch": {"totalHits": 904, "data": {"jobs": [job, {"title": "No link", "jobId": "1"}]}}})
    assert total == 904 and len(posts) == 1 and posts[0].posted_at == dt.date(2026, 10, 12) and "&show_apply=1" in posts[0].url

    calls = []

    class Client:
        async def request(self, method, url, **kw):
            start = kw["json"]["from"]
            calls.append(start)
            n = max(0, min(50, 120 - start))
            return _Resp({"refineSearch": {"totalHits": 120, "data": {"jobs": [{**job, "jobId": str(start + i)} for i in range(n)]}}})

    res = asyncio.run(readers.read_employer("phenom", "careers.bcg.com", Client(), _NoWait()))
    assert len(res.postings) == 120 and res.complete and calls == [0, 50, 100]
    assert readers.employer_ref("https://careers.bcg.com/global/en/search-results") == ("phenom", "careers.bcg.com")
    assert readers.employer_ref("https://example.com/widgets") is None


EY_PAGE = (
    '<div>Results 1 to 25 of 263</div><table><tbody><tr class="data-row"> <td class="colTitle" headers="hdrTitle"> <span class="jobTitle hidden-phone">'
    ' <a href="/ey/job/San-Francisco-Business-Consulting-Finance-R2R-&amp;-FP&amp;A-Manager-San-Francisco-Bay-CA-94105-2907/1441599833/" class="jobTitle-link">Business Consulting - Finance - R2R &amp; FP&amp;A Manager - San Francisco Bay</a>'
    ' </span></td> <td class="colLocation hidden-phone"> <span class="jobLocation"> San Francisco, CA, US </span> </td> <td class="colDate hidden-phone"> Oct 9, 2026 </td></tr>'
    '<tr class="data-row"> <td class="colTitle"> <span class="jobTitle hidden-phone"> <a href="/ey/job/Chicago-Mobility-Manager-IL-60606/1443008233/" class="jobTitle-link">Mobility Manager</a></span></td>'
    ' <td class="colLocation"> <span class="jobLocation">New York, NY, US, 10001-8604 +73 more…</span></td></tr></tbody></table>'
)


def test_successfactors_page_is_parsed_and_paged():
    posts, total = readers.parse_successfactors(EY_PAGE, "careers.ey.com")
    assert total == 263 and len(posts) == 2
    assert posts[0].ext_id == "1441599833" and posts[0].title.endswith("San Francisco Bay") and posts[0].location == "San Francisco, CA"
    assert posts[1].location == "New York, NY"
    assert posts[0].posted_at == dt.date(2026, 10, 9) and posts[0].url.startswith("https://careers.ey.com/ey/job/San-Francisco")
    assert readers.employer_ref("https://careers.ey.com/ey/job/Chicago-Mobility-Manager-IL-60606/1443008233/") == ("successfactors", "careers.ey.com|ey")

    urls = []

    class Client:
        async def request(self, method, url, **kw):
            urls.append(url)
            row = int(url.split("startrow=")[1])
            page = EY_PAGE.replace("1441599833", str(1000 + row)).replace("1443008233", str(2000 + row)).replace("of 263", "of 60")
            return _Resp(None, page if row < 60 else "")

    res = asyncio.run(readers.read_employer("successfactors", "careers.ey.com|ey", Client(), _NoWait()))
    assert len(res.postings) == 6 and res.complete and "optionsFacetsDD_country=US" in urls[0] and len(urls) == 3
    with pytest.raises(readers.ReaderError):
        class Bad:
            async def request(self, method, url, **kw):
                return _Resp(None, "<html>new layout</html>")
        asyncio.run(readers.read_employer("successfactors", "careers.ey.com|ey", Bad(), _NoWait()))


DAYFORCE_ANSWER = {
    "maxCount": 3, "offset": 0, "count": 3,
    "jobPostings": [
        {"jobPostingId": 8358, "jobTitle": "32791-VP, Product Management", "hasVirtualLocation": True, "postingStartTimestampUTC": "2026-10-05T05:00:00+00:00", "postingLocations": None},
        {"jobPostingId": 8344, "jobTitle": "10732-Senior Project Coordinator", "hasVirtualLocation": True, "postingStartTimestampUTC": "2026-09-30T04:00:00+00:00",
         "postingLocations": [{"formattedAddress": "United States", "locationType": 2, "isoCountryCode": "US", "stateCode": None, "city": None}]},
        {"jobPostingId": 8001, "jobTitle": "Revenue Cycle Analyst", "hasVirtualLocation": False, "postingStartTimestampUTC": "2026-09-01T04:00:00+00:00",
         "postingLocations": [{"formattedAddress": "Boston, MA, US", "isoCountryCode": "US", "stateCode": "MA", "city": "Boston"}]},
    ],
}


def test_dayforce_answer_is_parsed():
    assert readers.employer_ref("https://jobs.dayforcehcm.com/en-US/finthrive/CANDIDATEPORTAL/jobs/8354") == ("dayforce", "finthrive|CANDIDATEPORTAL|en-US")
    assert readers.employer_ref("https://jobs.dayforcehcm.com/") is None
    posts, total = readers.parse_dayforce(DAYFORCE_ANSWER, "finthrive", "CANDIDATEPORTAL", "en-US")
    assert total == 3 and [p.title for p in posts] == ["VP, Product Management", "Senior Project Coordinator", "Revenue Cycle Analyst"]
    assert posts[0].location == "Remote" and posts[0].work_type == "remote" and posts[1].work_type == "remote" and posts[2].location == "Boston, MA" and posts[2].work_type is None
    assert posts[0].url == "https://jobs.dayforcehcm.com/en-US/finthrive/CANDIDATEPORTAL/jobs/8358" and posts[0].posted_at == dt.date(2026, 10, 5)


def test_dayforce_reader_fetches_the_token_first_and_sends_it_back():
    calls = []

    class Client:
        async def request(self, method, url, **kw):
            calls.append((method, url, (kw.get("headers") or {}).get("x-csrf-token"), (kw.get("json") or {}).get("paginationStart")))
            return _Resp({"csrfToken": "tok123"} if method == "GET" else DAYFORCE_ANSWER)

    res = asyncio.run(readers.read_employer("dayforce", "finthrive|CANDIDATEPORTAL|en-US", Client(), _NoWait()))
    assert len(res.postings) == 3 and res.complete
    assert calls[0][:2] == ("GET", "https://jobs.dayforcehcm.com/api/auth/csrf")
    assert calls[1] == ("POST", "https://jobs.dayforcehcm.com/api/geo/finthrive/jobposting/search", "tok123", 0)
    assert known_name("dayforce", "finthrive|CANDIDATEPORTAL|en-US") == "FinThrive"

    class NoToken:
        async def request(self, method, url, **kw):
            return _Resp({"nope": 1})

    with pytest.raises(readers.ReaderError):
        asyncio.run(readers.read_employer("dayforce", "finthrive|CANDIDATEPORTAL|en-US", NoToken(), _NoWait()))


KPMG_CARD = (
    '<div class="holder--postings" data-value="list"> <div class="search--item mb-2 mb-md-3 search--experienced "> <a href="/jobdetail/?jobId=135758" data-id="1" class="box-shadow d-block">'
    ' <div class="grid-view"> <div class="px-3 py-1 eyebrow">Experienced</div> <div class="p-3"><div class="h4 mb-4">Experienced Associate - Global Trade - Data Analytics</div>'
    ' <div class="text-xs text-dark-grey">17 Locations</div></div></div> <div class="list-view d-flex justify-content-between"> <div class="p-2 ps-4">'
    ' <div class="h5 text-dark-grey">Experienced Associate - Global Trade - Data Analytics</div>'
    ' <div class="text-xs text-dark-grey">Tax | Atlanta, GA; Boston, MA; Chicago, IL</div> </div></div> </a></div>'
    ' <div class="search--item mb-2 "> <a href="/jobdetail/?jobId=139052" class="box-shadow d-block"> <div class="list-view"> <div class="p-2">'
    ' <div class="h5 text-dark-grey">Associate Director - Corporate Card Programs</div> <div class="text-xs text-dark-grey">Business Support Services | Montvale, NJ</div> </div></div></a></div>'
)


def test_kpmg_cards_are_parsed_and_paged():
    assert readers.employer_ref("https://www.kpmguscareers.com/job-search/?spage=2") == ("kpmg", "www.kpmguscareers.com")
    assert readers.employer_ref("https://www.kpmguscareers.com/about") is None
    a, b = readers.parse_kpmg(KPMG_CARD)
    assert a.ext_id == "135758" and a.title == "Experienced Associate - Global Trade - Data Analytics" and a.location == "Atlanta, GA; Boston, MA; Chicago, IL"
    assert b.location == "Montvale, NJ" and b.url == "https://www.kpmguscareers.com/jobdetail/?jobId=139052"

    urls = []

    class Client:
        async def request(self, method, url, **kw):
            urls.append(url)
            n = len(urls)
            return _Resp(None, KPMG_CARD.replace("135758", str(n * 10 + 1)).replace("139052", str(n * 10 + 2)) if n <= 2 else "<html>no more</html>")

    res = asyncio.run(readers.read_employer("kpmg", "www.kpmguscareers.com", Client(), _NoWait()))
    assert len(res.postings) == 4 and res.complete and urls[1].endswith("?spage=2") and "spage" not in urls[0]
    assert known_name("kpmg", "www.kpmguscareers.com") == "KPMG"


def test_workable_list_keeps_the_description_when_the_answer_carries_it():
    w = readers.parse_workable({"name": "Acme", "jobs": [{"title": "Billing Lead", "shortcode": "AB12", "url": "https://apply.workable.com/j/AB12", "description": "<p>Own claims and denials.</p>"}]}, "acme")
    assert "claims and denials" in w[0].description
    plain = readers.parse_workable({"name": "Acme", "jobs": [{"title": "Billing Lead", "shortcode": "AB12"}]}, "acme")
    assert plain[0].description is None
