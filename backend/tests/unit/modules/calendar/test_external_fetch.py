"""Unit tests of the fetch of an external calendar (spec 000722).

The fetcher runs against an `httpx.MockTransport`, so a test sees every request that
leaves the fetcher, with the address it connects to.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx

from app.modules.calendar.external_fetch import (
    MAX_REDIRECTS,
    Fetched,
    HttpFeedFetcher,
)

PUBLIC = "93.184.216.34"
Handler = Callable[[httpx.Request], httpx.Response]


def _fetcher(
    handler: Handler, hosts: dict[str, list[str]], **limits: float | int
) -> tuple[HttpFeedFetcher, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return (
        HttpFeedFetcher(
            resolver=lambda host: hosts.get(host, []),
            client_factory=lambda _t: httpx.AsyncClient(transport=httpx.MockTransport(_record)),
            **limits,  # type: ignore[arg-type]
        ),
        seen,
    )


def _run(fetcher: HttpFeedFetcher, url: str) -> Fetched:
    return asyncio.run(fetcher.fetch(url))


def test_fetches_through_the_checked_address() -> None:
    fetcher, seen = _fetcher(
        lambda _r: httpx.Response(200, content=b"BEGIN:VCALENDAR"),
        {"cal.example.org": ["2606:2800:220:1::1", PUBLIC]},
    )
    assert _run(fetcher, "https://cal.example.org/a.ics?x=1") == Fetched(data=b"BEGIN:VCALENDAR")
    assert str(seen[0].url) == f"https://{PUBLIC}/a.ics?x=1"
    assert seen[0].headers["host"] == "cal.example.org"
    assert seen[0].extensions["sni_hostname"] == "cal.example.org"


def test_private_address_gets_no_request() -> None:
    """§F/meetings/calendar/000722: a URL that resolves to a private address is not fetched."""
    fetcher, seen = _fetcher(
        lambda _r: httpx.Response(200, content=b"x"),
        {"intern.example.org": ["10.0.0.5"], "mixed.example.org": [PUBLIC, "127.0.0.1"]},
    )
    for url in (
        "https://intern.example.org/a.ics",
        "https://mixed.example.org/a.ics",
        "https://169.254.169.254/latest",
        "https://unknown.example.org/a.ics",
        "http://cal.example.org/a.ics",
        "https:///a.ics",
    ):
        assert _run(fetcher, url) == Fetched(error="blocked")
    assert seen == []


def test_redirect_runs_the_guard_again() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "a.example.org":
            return httpx.Response(302, headers={"location": "https://intern.example.org/x"})
        return httpx.Response(200, content=b"secret")

    fetcher, seen = _fetcher(
        _handler, {"a.example.org": [PUBLIC], "intern.example.org": ["192.168.1.1"]}
    )
    assert _run(fetcher, "https://a.example.org/a.ics") == Fetched(error="blocked")
    assert len(seen) == 1


def test_follows_a_relative_redirect() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a.ics":
            return httpx.Response(301, headers={"location": "/b.ics"})
        return httpx.Response(200, content=b"ok")

    fetcher, seen = _fetcher(_handler, {"a.example.org": [PUBLIC]})
    assert _run(fetcher, "https://a.example.org/a.ics") == Fetched(data=b"ok")
    assert [r.url.path for r in seen] == ["/a.ics", "/b.ics"]


def test_redirect_loop_and_missing_location() -> None:
    loop, seen = _fetcher(
        lambda _r: httpx.Response(307, headers={"location": "/again"}),
        {"a.example.org": [PUBLIC]},
    )
    assert _run(loop, "https://a.example.org/a.ics") == Fetched(error="redirect")
    assert len(seen) == MAX_REDIRECTS + 1
    bare, _ = _fetcher(lambda _r: httpx.Response(302), {"a.example.org": [PUBLIC]})
    assert _run(bare, "https://a.example.org/a.ics") == Fetched(error="redirect")


def test_status_size_and_transport_errors() -> None:
    hosts = {"a.example.org": [PUBLIC]}
    url = "https://a.example.org/a.ics"
    missing, _ = _fetcher(lambda _r: httpx.Response(404), hosts)
    assert _run(missing, url) == Fetched(error="status")
    big, _ = _fetcher(lambda _r: httpx.Response(200, content=b"x" * 200_000), hosts, max_bytes=1000)
    assert _run(big, url) == Fetched(error="size")

    def _down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    down, _ = _fetcher(_down, hosts)
    assert _run(down, url) == Fetched(error="unreachable")


def test_deadline_covers_the_whole_fetch() -> None:
    async def _slow(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, content=b"late")

    fetcher = HttpFeedFetcher(
        timeout_seconds=0.05,
        resolver=lambda _host: [PUBLIC],
        client_factory=lambda _t: httpx.AsyncClient(transport=httpx.MockTransport(_slow)),
    )
    assert _run(fetcher, "https://a.example.org/a.ics") == Fetched(error="timeout")


def test_default_client_follows_no_redirect() -> None:
    client = HttpFeedFetcher().client_factory(1.0)
    assert client.follow_redirects is False
    asyncio.run(client.aclose())
