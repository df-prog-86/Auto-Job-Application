"""
The one way this app fetches a web page whose address it did not choose itself (a search result, a pasted link, a link found
on a page). Every request, and every redirect, is checked BEFORE it is made:

  * only http and https, on ordinary web ports, with no user name or password in the address;
  * the address's host must resolve only to public internet addresses: never this computer, a home or office network,
    a cloud metadata address (169.254.169.254) or any other private range, whether written as a number or a name;
  * at most 5 redirects, each one checked again;
  * the page is cut off at 2 MB so a huge or endless answer cannot fill memory.

A refusal raises UnsafeUrlError, which is an httpx.HTTPError, so callers that already treat "could not fetch" as "unknown"
keep working. One gap remains by design: a site could change its DNS answer between our check and the connection. Hosts we
only ever read through fixed public APIs (the job-list readers) do not use this module.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

ALLOWED_PORTS = {None, 80, 443, 8080, 8443}
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5
_BAD_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home", ".corp", ".intranet")


class UnsafeUrlError(httpx.TransportError):
    """The address is not one this app will fetch (and nothing was sent)."""


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved or ip.is_unspecified)


def is_public_host(url: str) -> bool:
    """A fast check that needs no network: False for localhost, local-looking names and private numeric addresses."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return False
    if not host or host == "localhost" or host.endswith(_BAD_SUFFIXES) or "." not in host and ":" not in host:
        return False
    if port not in ALLOWED_PORTS:
        return False
    try:
        return _ip_is_public(ipaddress.ip_address(host))
    except ValueError:
        return True


async def check_url(url: str) -> None:
    """Raises UnsafeUrlError unless the address is safe to fetch. Looks the name up, so a name that points at a private address is caught."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError("not a valid web address") from exc
    if parts.scheme not in ("http", "https"):
        raise UnsafeUrlError("only http and https addresses are fetched")
    if parts.username or parts.password:
        raise UnsafeUrlError("addresses with a user name or password are not fetched")
    if not is_public_host(url):
        raise UnsafeUrlError("that address is not on the public internet")
    host = parts.hostname or ""
    try:
        ipaddress.ip_address(host)
        return  # a public numeric address: nothing to look up
    except ValueError:
        pass
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeUrlError("that name could not be looked up") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(_ip_is_public(ipaddress.ip_address(a.split("%")[0])) for a in addresses):
        raise UnsafeUrlError("that name points at a private address")


async def safe_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    max_redirects: int = MAX_REDIRECTS,
    max_bytes: int = MAX_BYTES,
) -> httpx.Response:
    """GET with every hop checked. Returns a normal httpx.Response (final address in .url, body cut at max_bytes)."""
    current = url.strip()
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _hop in range(max_redirects + 1):
            await check_url(current)
            async with client.stream("GET", current, headers=headers) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    continue
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) >= max_bytes:
                        break
                keep: dict[str, Any] = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
                return httpx.Response(resp.status_code, headers=keep, content=bytes(body[:max_bytes]), request=resp.request)
    raise UnsafeUrlError("too many redirects")
