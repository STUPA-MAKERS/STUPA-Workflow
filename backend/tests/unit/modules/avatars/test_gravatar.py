"""Unit tests of the Gravatar fetcher: hash, size buckets, sniffing, the HTTP path."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import httpx
import pytest

from app.modules.avatars.gravatar import (
    MAX_IMAGE_BYTES,
    AvatarImage,
    HttpGravatarFetcher,
    gravatar_hash,
    gravatar_url,
    size_bucket,
    sniff_avatar,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 32
DIGEST = "a" * 64


def _resolver(*ips: str) -> Callable[[str], list[str]]:
    return lambda _host: list(ips)


def _fetcher(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    resolver: Callable[[str], list[str]] | None = None,
    timeout: float = 2.0,
) -> HttpGravatarFetcher:
    transport = httpx.MockTransport(handler)
    return HttpGravatarFetcher(
        timeout_seconds=timeout,
        resolver=resolver or _resolver("192.0.73.2"),
        client_factory=lambda: httpx.AsyncClient(transport=transport, follow_redirects=False),
    )


def test_hash_is_sha256_of_the_trimmed_lower_case_address() -> None:
    expected = hashlib.sha256(b"mara.keller@example.org").hexdigest()
    assert gravatar_hash("  Mara.Keller@Example.ORG \n") == expected
    assert len(expected) == 64


@pytest.mark.parametrize(
    ("requested", "bucket"),
    [(1, 64), (64, 64), (65, 128), (80, 128), (128, 128), (200, 256), (512, 256)],
)
def test_size_rounds_up_to_a_bucket(requested: int, bucket: int) -> None:
    assert size_bucket(requested) == bucket


def test_url_uses_the_fixed_host_and_asks_for_a_404() -> None:
    assert gravatar_url(DIGEST, 64) == f"https://gravatar.com/avatar/{DIGEST}?s=64&d=404"


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (GIF, "image/gif"),
        (b"GIF87a" + b"\x00" * 8, "image/gif"),
        (WEBP, "image/webp"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", None),
        (b"<html></html>", None),
        (b"\x00\x00\x01\x00", None),  # an icon is not an avatar
        (b"", None),
    ],
)
def test_sniff_accepts_raster_images_only(data: bytes, mime: str | None) -> None:
    assert sniff_avatar(data) == mime


def test_etag_comes_from_the_bytes_only() -> None:
    a = AvatarImage(mime="image/png", data=PNG)
    assert a.etag == AvatarImage(mime="image/png", data=PNG).etag
    assert a.etag != AvatarImage(mime="image/png", data=PNG + b"\x01").etag
    assert a.etag.startswith('"') and a.etag.endswith('"')
    assert DIGEST[:16] not in a.etag


async def test_found_image_is_returned_and_the_request_is_pinned() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})

    result = await _fetcher(handler).fetch(DIGEST, 128)
    assert result.kind == "found"
    assert result.image == AvatarImage(mime="image/png", data=PNG)
    request = seen[0]
    # The client connects to the checked IP and keeps the host for routing and TLS.
    assert request.url.host == "192.0.73.2"
    assert request.url.path == f"/avatar/{DIGEST}"
    assert request.url.params["s"] == "128"
    assert request.url.params["d"] == "404"
    assert request.headers["Host"] == "gravatar.com"
    assert request.extensions["sni_hostname"] == "gravatar.com"


async def test_ipv4_target_is_preferred() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(404)

    await _fetcher(handler, resolver=_resolver("2a04:fa87:fffd::c000:4902", "192.0.73.2")).fetch(
        DIGEST, 64
    )
    assert hosts == ["192.0.73.2"]


async def test_ipv6_only_target_is_used() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(404)

    await _fetcher(handler, resolver=_resolver("2a04:fa87:fffd::c000:4902")).fetch(DIGEST, 64)
    assert hosts == ["2a04:fa87:fffd::c000:4902"]


async def test_404_is_a_miss() -> None:
    result = await _fetcher(lambda _r: httpx.Response(404)).fetch(DIGEST, 64)
    assert result.kind == "missing" and result.image is None


@pytest.mark.parametrize("status", [301, 429, 500, 503])
async def test_other_status_is_a_failure(status: int) -> None:
    result = await _fetcher(lambda _r: httpx.Response(status)).fetch(DIGEST, 64)
    assert result.kind == "failed"


async def test_non_image_content_is_a_miss() -> None:
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    result = await _fetcher(
        lambda _r: httpx.Response(200, content=svg, headers={"Content-Type": "image/png"})
    ).fetch(DIGEST, 64)
    assert result.kind == "missing"


async def test_too_large_body_is_a_miss() -> None:
    body = PNG + b"\x00" * MAX_IMAGE_BYTES
    result = await _fetcher(lambda _r: httpx.Response(200, content=body)).fetch(DIGEST, 64)
    assert result.kind == "missing"


async def test_transport_error_is_a_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = await _fetcher(handler).fetch(DIGEST, 64)
    assert result.kind == "failed"


async def test_total_deadline_is_a_failure() -> None:
    import asyncio

    class _Slow(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(5)
            return httpx.Response(200, content=PNG)  # pragma: no cover - never reached

    fetcher = HttpGravatarFetcher(
        timeout_seconds=0.05,
        resolver=_resolver("192.0.73.2"),
        client_factory=lambda: httpx.AsyncClient(transport=_Slow()),
    )
    assert (await fetcher.fetch(DIGEST, 64)).kind == "failed"


@pytest.mark.parametrize("ips", [("10.0.0.5",), ("169.254.169.254",), ("127.0.0.1",), ()])
async def test_internal_or_unresolved_target_is_blocked(ips: tuple[str, ...]) -> None:
    called: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        called.append(request)
        return httpx.Response(200, content=PNG)

    result = await _fetcher(handler, resolver=_resolver(*ips)).fetch(DIGEST, 64)
    assert result.kind == "failed"
    assert called == []


def test_default_client_factory_builds_a_client_without_redirects() -> None:
    fetcher = HttpGravatarFetcher(timeout_seconds=1.5)
    client = fetcher._client_factory()
    try:
        assert client.follow_redirects is False
        assert client.timeout.connect == 1.5
    finally:
        import asyncio

        asyncio.run(client.aclose())
