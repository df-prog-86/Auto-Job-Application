import httpx
import pytest

from app.services import safe_fetch


def test_quick_check_refuses_this_computer_and_private_networks():
    f = safe_fetch.is_public_host
    assert f("https://careers.example.com/j") and f("http://93.184.216.34/x")
    for bad in ("http://localhost:8765/x", "http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data",
                "http://[::1]/", "http://[::ffff:10.0.0.1]/", "http://printer.local/", "http://intranet/", "http://100.64.0.1/",
                "https://example.com:6379/", "http://0.0.0.0/"):
        assert not f(bad), bad


async def test_check_url_refuses_bad_schemes_credentials_and_names_that_point_inside(monkeypatch):
    async def fake_lookup(self, host, port, **kw):
        table = {"evil.example.com": "10.1.2.3", "good.example.com": "93.184.216.34", "mixed.example.com": None}
        if host == "mixed.example.com":
            return [(2, 1, 6, "", ("93.184.216.34", port)), (2, 1, 6, "", ("192.168.0.9", port))]
        if host not in table:
            raise OSError("no such name")
        return [(2, 1, 6, "", (table[host], port))]

    import asyncio

    monkeypatch.setattr(asyncio.get_running_loop().__class__, "getaddrinfo", fake_lookup, raising=True)
    await safe_fetch.check_url("https://good.example.com/job")
    for bad in ("ftp://good.example.com/x", "file:///etc/passwd", "https://user:pw@good.example.com/", "https://evil.example.com/", "https://mixed.example.com/",
                "https://nowhere.example.com/"):
        with pytest.raises(safe_fetch.UnsafeUrlError):
            await safe_fetch.check_url(bad)
    assert issubclass(safe_fetch.UnsafeUrlError, httpx.HTTPError)  # callers that treat "could not fetch" as "unknown" keep working


async def test_safe_get_checks_every_redirect_and_caps_the_size(monkeypatch):
    seen = []

    async def ok(url):
        seen.append(url)
        if "inside" in url:
            raise safe_fetch.UnsafeUrlError("private")

    monkeypatch.setattr(safe_fetch, "check_url", ok)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://inside.example.com/secret"})
        if request.url.path == "/big":
            return httpx.Response(200, content=b"x" * 5000)
        return httpx.Response(200, text="ok")

    real = httpx.AsyncClient
    monkeypatch.setattr(safe_fetch.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(safe_fetch.UnsafeUrlError):
        await safe_fetch.safe_get("https://a.example.com/start")      # the redirect is refused before it is followed
    assert seen == ["https://a.example.com/start", "https://inside.example.com/secret"]
    resp = await safe_fetch.safe_get("https://a.example.com/big", max_bytes=1000)
    assert len(resp.content) == 1000 and str(resp.url) == "https://a.example.com/big"
    assert (await safe_fetch.safe_get("https://a.example.com/fine")).text == "ok"


async def test_pasted_links_to_this_computer_are_refused_before_any_request():
    from app.services.discovery import manual_extraction

    with pytest.raises(manual_extraction.ManualExtractionError):
        await manual_extraction.fetch_page("http://127.0.0.1:8765/api/v1/profile")


def test_job_list_readers_only_contact_known_hiring_systems():
    from app.services.jobcache.readers import reader_url_allowed as ok

    assert ok("https://boards-api.greenhouse.io/v1/boards/acme/jobs") and ok("https://api.lever.co/v0/postings/acme") and ok("https://x.wd5.myworkdayjobs.com/wday/cxs/x/y/jobs")
    assert ok("https://careers.bcg.com/widgets") and ok("https://acme.bamboohr.com/careers/list") and ok("https://api.ashbyhq.com/posting-api/job-board/acme")
    for bad in ("http://boards-api.greenhouse.io/x", "https://evil.com/x", "https://greenhouse.io.evil.com/x", "https://evil.com#.myworkdayjobs.com/",
                "https://api.ashbyhq.com/posting-api/job-board/../../admin", "https://api.ashbyhq.com/a%2fb", "https://127.0.0.1/x",
                "https://u:p@api.lever.co/v0/postings/x", "https://api.lever.co:8443/x", "https://api.lever.co/a b"):
        assert not ok(bad), bad
