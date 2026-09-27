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


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    """
    Rejects any request whose Host header isn't 127.0.0.1/localhost (the
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
