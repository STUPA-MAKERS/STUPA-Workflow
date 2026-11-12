"""Fetch the ICS feed of an external calendar through the SSRF guard.

Only the worker fetches. The address is input of an admin, so the fetcher takes only
`https`, checks the resolved addresses of every hop with the SSRF guard and connects to
a checked address (`pin_url`), with the host of the URL as the `Host` header and the TLS
SNI. The client follows no redirect by itself: the fetcher reads the `Location` header
and runs the whole check again for the new address, at most `MAX_REDIRECTS` times. One
deadline covers every lookup, connect and read, and the body stops at `MAX_BYTES`.

A failure is a short code and never the text of an exception, because that text can
hold a resolved internal address. The admin page shows the code as a sentence.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from app.shared.ssrf import Resolver, SsrfError, assert_allowed_url, default_resolver, pin_url

logger = logging.getLogger(__name__)

#: The limits of one fetch.
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 3
_CHUNK = 64 * 1024

_REDIRECTS = frozenset({301, 302, 303, 307, 308})

#: The causes of a failed fetch. ``format`` comes from the reader of the feed.
FetchError = Literal["blocked", "timeout", "unreachable", "status", "size", "redirect", "format"]


@dataclass(frozen=True, slots=True)
class Fetched:
    """The result of one fetch: the bytes, or the cause of the failure."""

    data: bytes | None = None
    error: FetchError | None = None


class FeedFetcher(Protocol):
    """Fetch the bytes of one feed address."""

    async def fetch(self, url: str) -> Fetched:
        """Fetch ``url``."""
        ...


def _prefer_ipv4(ips: list[str]) -> str:
    """Pick the first IPv4 address, else the first address.

    A container often has no IPv6 route, so an IPv4 target connects more reliably.
    """
    return next(
        (ip for ip in ips if isinstance(ipaddress.ip_address(ip), ipaddress.IPv4Address)),
        ips[0],
    )


def _client(timeout_seconds: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(timeout_seconds))


async def _take(stream: AsyncIterator[bytes], got: bytes, limit: int) -> bytes | None:
    """Read the stream to its end. None when it holds more than ``limit`` bytes.

    The stream gives pieces of `_CHUNK` bytes, so the recursion is at most
    ``limit / _CHUNK`` calls deep.
    """
    chunk = await anext(stream, None)
    if chunk is None:
        return got
    return None if len(got) + len(chunk) > limit else await _take(stream, got + chunk, limit)


@dataclass(frozen=True, slots=True)
class HttpFeedFetcher:
    """Fetch a feed over HTTPS with a pinned address per hop.

    A test injects the DNS resolver and the HTTP client factory.
    """

    timeout_seconds: float = TIMEOUT_SECONDS
    max_bytes: int = MAX_BYTES
    resolver: Resolver = default_resolver
    client_factory: Callable[[float], httpx.AsyncClient] = _client

    async def fetch(self, url: str) -> Fetched:
        """Fetch the feed under one deadline for all hops."""
        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await self._follow(url, MAX_REDIRECTS)
        except TimeoutError:
            return Fetched(error="timeout")
        except httpx.HTTPError as exc:
            logger.warning("external calendar fetch failed: %s", type(exc).__name__)
            return Fetched(error="unreachable")

    async def _follow(self, url: str, hops: int) -> Fetched:
        """Fetch one hop and follow its redirect after a new guard check."""
        result = await self._hop(url)
        if isinstance(result, Fetched):
            return result
        return await self._follow(result, hops - 1) if hops > 0 else Fetched(error="redirect")

    async def _hop(self, url: str) -> Fetched | str:
        """Request one address. Return the result, or the address of a redirect."""
        host = urlsplit(url).hostname
        if urlsplit(url).scheme.lower() != "https" or not host:
            return Fetched(error="blocked")
        try:
            ips = await asyncio.to_thread(assert_allowed_url, url, resolver=self.resolver)
        except SsrfError:
            logger.warning("external calendar fetch blocked by the ssrf guard")
            return Fetched(error="blocked")
        ip_url, host_header = pin_url(url, _prefer_ipv4(ips))
        async with self.client_factory(self.timeout_seconds) as client:
            request = client.build_request(
                "GET",
                ip_url,
                headers={"Host": host_header, "Accept": "text/calendar, */*;q=0.1"},
                extensions={"sni_hostname": host},
            )
            response = await client.send(request, stream=True)
            try:
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("location")
                    return urljoin(url, location) if location else Fetched(error="redirect")
                if response.status_code != 200:
                    return Fetched(error="status")
                return await self._body(response)
            finally:
                await response.aclose()

    async def _body(self, response: httpx.Response) -> Fetched:
        """Read the body and stop above the size limit."""
        data = await _take(response.aiter_bytes(_CHUNK), b"", self.max_bytes)
        return Fetched(error="size") if data is None else Fetched(data=data)
