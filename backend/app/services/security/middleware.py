"""
Request-level guards for the extension-facing API surface (spec §8.2):
acceptable Host header, allowlisted origin, and a reasonable body-size cap.
Token verification itself happens per-route via the `require_extension_auth`
dependency (app/api/deps.py), not here, since not every route needs it
(the dashboard's own routes are same-origin and browser-session-based, not
extension-token-based).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

_ACCEPTABLE_HOSTS = {"127.0.0.1", "localhost"}


def origin_allowed(origin: str) -> bool:
    """
    The dashboard (this app's own address, or the dev server), the paired Chrome extension, and anything listed in
    EXTENSION_ORIGIN_ALLOWLIST. Any other website is refused, so a page open in another tab cannot trigger actions here.
    """
    if origin.startswith("chrome-extension://"):  # a browser sets this itself; a web page cannot write it
        return True
    port = settings.LOCAL_API_PORT
    own = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    if settings.APP_ENV != "production":
        own |= {"http://127.0.0.1:5173", "http://localhost:5173"}  # the dashboard's dev server
    return origin in own or origin in (settings.EXTENSION_ORIGIN_ALLOWLIST or [])


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    """
    Rejects any request that comes from another website (Origin / Sec-Fetch-Site), and any request whose Host header isn't 127.0.0.1/localhost (the
    server also only *binds* to 127.0.0.1, but this catches DNS-rebinding
    style attempts that target the right IP with a spoofed Host header) and
    enforces a maximum request body size before it reaches a handler.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        host = (request.headers.get("host") or "").split(":")[0]
        if host and host not in _ACCEPTABLE_HOSTS:
            return JSONResponse(
                status_code=400, content={"detail": "Unacceptable Host header"}
            )

        origin = request.headers.get("origin")
        if origin is not None and not origin_allowed(origin):
            return JSONResponse(status_code=403, content={"detail": "Requests from other websites are not accepted"})
        # Browsers label every request with where it came from. A "cross-site" request that is not opening a page (an image,
        # a script, a background request from another site's page) is never one this app should answer.
        if request.headers.get("sec-fetch-site") == "cross-site" and request.headers.get("sec-fetch-mode") != "navigate" and not (origin or "").startswith("chrome-extension://"):
            return JSONResponse(status_code=403, content={"detail": "Requests from other websites are not accepted"})

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > settings.MAX_REQUEST_BODY_BYTES:
                    return JSONResponse(
                        status_code=413, content={"detail": "Request body too large"}
                    )
            except ValueError:
                pass

        return await call_next(request)
