"""Address keys, so a posting found here is recognised as the same one you already saved or were already shown."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_LOCALE = re.compile(r"^/[a-z]{2}-[A-Za-z]{2}(?=/)")
_WD_REQ = re.compile(r"_([A-Za-z]{1,4}-?\d{3,})(?:/|$)")
_GH_ID = re.compile(r"(?:/jobs/|[?&](?:gh_jid|token)=)(\d+)")


def url_key(url: str) -> str:
    """host + path, no scheme, query, fragment or trailing slash. Identical to web_search.url_key (a test keeps them equal)."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}".lower()


def loose_keys(url: str) -> set[str]:
    """
    Every way the same posting might have been written: the plain key, the key without a Workday language segment
    (/en-US/), a Workday requisition number, and a Greenhouse job number.
    """
    keys = {url_key(url)}
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    if host.endswith(".myworkdayjobs.com"):
        keys.add(f"{host}{_LOCALE.sub('', path)}".lower())
        keys.add(f"{host}{_LOCALE.sub('', re.sub(r'/(apply|login)(/.*)?$', '', path, flags=re.I))}".lower())
        m = _WD_REQ.search(path + "/")
        if m:
            keys.add(f"wd:{host}:{m.group(1).lower()}")
    if "greenhouse" in host or "gh_jid" in parts.query:
        m = _GH_ID.search(path + ("?" + parts.query if parts.query else ""))
        if m:
            keys.add(f"gh:{m.group(1)}")
    return keys
