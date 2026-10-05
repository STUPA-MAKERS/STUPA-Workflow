"""Gravatar lookup through one fixed host.

The browser never contacts Gravatar. The API computes the SHA-256 hash of the
normalised e-mail address, fetches ``https://gravatar.com/avatar/<hash>?s=<n>&d=404``
and sends the image bytes on from its own origin. So neither the e-mail address nor
its hash reaches the client, and the CSP needs no external image host.

The URL is not user input: the host is a constant, the hash is hex and the size comes
from a fixed set. The SSRF guard of the webhooks still checks the resolved IP and
pins it against DNS rebinding, so a manipulated resolver cannot point the API at an
internal address.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from app.modules.webhooks.ssrf import (
    Resolver,
    SsrfError,
    assert_allowed_url,
    default_resolver,
    pin_url,
)

logger = logging.getLogger("app.avatars")

GRAVATAR_HOST = "gravatar.com"

# The sizes the proxy asks Gravatar for. A request rounds up to the next one, so the
# cache holds at most three entries per person.
SIZE_BUCKETS: tuple[int, ...] = (64, 128, 256)

# Upper limit of one image. Gravatar sends a few KiB; a larger body is refused.
MAX_IMAGE_BYTES = 512 * 1024

AvatarMime = Literal["image/png", "image/jpeg", "image/gif", "image/webp"]


def gravatar_hash(email: str) -> str:
    """Return the SHA-256 hex digest of the trimmed, lower-case e-mail address.

    Gravatar accepts SHA-256 as well as MD5. SHA-256 does not give a cheap reverse
    lookup of the address.
    """
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def size_bucket(requested: int) -> int:
    """Round the requested pixel size up to the next size in ``SIZE_BUCKETS``."""
    for size in SIZE_BUCKETS:
        if requested <= size:
            return size
    return SIZE_BUCKETS[-1]


def gravatar_url(digest: str, size: int) -> str:
    """Build the Gravatar URL. ``d=404`` makes Gravatar answer 404 without an image."""
    return f"https://{GRAVATAR_HOST}/avatar/{digest}?s={size}&d=404"


def sniff_avatar(data: bytes) -> AvatarMime | None:
    """Get the image type from the magic bytes.

    Returns:
        The MIME type of a PNG, JPEG, GIF or WebP image. ``None`` for all other
        content, for example SVG or HTML, which the proxy never passes on.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(frozen=True, slots=True)
class AvatarImage:
    """Image bytes plus their sniffed MIME type."""

    mime: AvatarMime
    data: bytes

    @property
    def etag(self) -> str:
        """Strong ETag from the image bytes. It holds no part of the e-mail hash."""
        return '"' + hashlib.sha256(self.data).hexdigest()[:32] + '"'


FetchKind = Literal["found", "missing", "failed"]


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Result of one Gravatar fetch.

    ``found`` carries the image. ``missing`` means that Gravatar has no image for the
    hash, or sent content that is not an image. ``failed`` is a transient error
    (timeout, transport error, an unexpected status).
    """

    kind: FetchKind
    image: AvatarImage | None = None


class GravatarFetcher(Protocol):
    async def fetch(self, digest: str, size: int) -> FetchResult: ...


def _prefer_ipv4(ips: list[str]) -> str:
    """Pick the first IPv4 address, else the first address.

    A container often has no IPv6 route, so an IPv4 target connects more reliably.
    """
    for ip in ips:
        if isinstance(ipaddress.ip_address(ip), ipaddress.IPv4Address):
            return ip
    return ips[0]


class HttpGravatarFetcher:
    """Fetch an avatar from gravatar.com over HTTPS.

    The fetcher resolves the host, checks the IPs with the SSRF guard and connects
    to the checked IP. The ``Host`` header and the TLS SNI keep ``gravatar.com``, so
    the certificate check still applies. Redirects are not followed. One total
    deadline covers the DNS lookup, the connect and all reads. When the deadline
    stops a slow lookup, the resolver thread runs on to its own end in the
    background, but the request does not wait for it.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float,
        resolver: Resolver = default_resolver,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._resolver = resolver
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(
                follow_redirects=False, timeout=httpx.Timeout(timeout_seconds)
            )
        )

    async def fetch(self, digest: str, size: int) -> FetchResult:
        url = gravatar_url(digest, size)
        try:
            async with asyncio.timeout(self._timeout):
                try:
                    ips = await asyncio.to_thread(
                        assert_allowed_url,
                        url,
                        allowlist=(GRAVATAR_HOST,),
                        resolver=self._resolver,
                    )
                except SsrfError:
                    # The detail holds the resolved IP; keep it out of the log.
                    logger.warning("gravatar fetch blocked by the ssrf guard")
                    return FetchResult("failed")
                ip_url, host_header = pin_url(url, _prefer_ipv4(ips))
                async with self._client_factory() as client:
                    request = client.build_request(
                        "GET", ip_url, headers={"Host": host_header, "Accept": "image/*"}
                    )
                    request.extensions["sni_hostname"] = GRAVATAR_HOST
                    response = await client.send(request, stream=True)
                    try:
                        return await _read(response)
                    finally:
                        await response.aclose()
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("gravatar fetch failed: %s", type(exc).__name__)
            return FetchResult("failed")


async def _read(response: httpx.Response) -> FetchResult:
    """Turn a Gravatar response into a ``FetchResult`` under the size cap."""
    if response.status_code == 404:
        return FetchResult("missing")
    if response.status_code != 200:
        return FetchResult("failed")
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > MAX_IMAGE_BYTES:
            return FetchResult("missing")
    data = bytes(body)
    mime = sniff_avatar(data)
    if mime is None:
        return FetchResult("missing")
    return FetchResult("found", AvatarImage(mime=mime, data=data))
