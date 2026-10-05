"""Unit tests of the avatar endpoints with TestClient and dependency_overrides."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.avatars.cache import CachedAvatar, RedisAvatarCache
from app.modules.avatars.gravatar import AvatarImage, FetchResult, HttpGravatarFetcher
from app.modules.avatars.router import (
    get_avatar_cache,
    get_gravatar_fetcher,
)
from app.settings import Settings, get_settings, load_settings
from app.shared.antiabuse import get_rate_limiter
from app.shared.ratelimit import InMemoryRateLimiter, RateLimiter
from tests._support.auth_fakes import fake_session, result

SETTINGS = load_settings(
    database_url="postgresql+asyncpg://x/y",
    session_secret="session-secret-0123",
    magic_link_secret="magic-link-secret-0",
    cookie_secure=False,
    gravatar_cache_ttl_seconds=86_400,
    rl_avatar_per_hour=3,
)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
IMAGE = AvatarImage(mime="image/png", data=PNG)
EMAIL = "Mara.Keller@example.org"
DIGEST = hashlib.sha256(EMAIL.lower().encode()).hexdigest()
ME = Principal(sub="u1", email=EMAIL, display_name="Mara Keller")


class _Cache:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, int], CachedAvatar] = {}

    async def get(self, digest: str, size: int) -> CachedAvatar | None:
        return self.entries.get((digest, size))

    async def put(
        self, digest: str, size: int, image: AvatarImage | None, *, ttl_seconds: int
    ) -> None:
        self.entries[(digest, size)] = CachedAvatar(image)


class _Fetcher:
    def __init__(self, result: FetchResult) -> None:
        self.result = result
        self.calls: list[tuple[str, int]] = []

    async def fetch(self, digest: str, size: int) -> FetchResult:
        self.calls.append((digest, size))
        return self.result


def _client(
    db: object,
    principal: Principal | None = ME,
    *,
    fetcher: _Fetcher | None = None,
    cache: _Cache | None = None,
    limiter: RateLimiter | None = None,
    settings: Settings = SETTINGS,
) -> TestClient:
    app = create_app(settings)

    async def _fake_db() -> AsyncIterator[object]:
        yield db

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = _fake_db
    if principal is not None:
        app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_gravatar_fetcher] = lambda: fetcher or _Fetcher(
        FetchResult("found", IMAGE)
    )
    app.dependency_overrides[get_avatar_cache] = lambda: cache or _Cache()
    app.dependency_overrides[get_rate_limiter] = lambda: limiter or InMemoryRateLimiter()
    return TestClient(app, follow_redirects=False)


def _id_url(pid: uuid.UUID | None = None, size: int | None = None) -> str:
    url = f"/api/principals/{pid or uuid.uuid4()}/avatar"
    return url if size is None else f"{url}?s={size}"


def test_image_of_a_principal() -> None:
    fetcher = _Fetcher(FetchResult("found", IMAGE))
    db = fake_session(result(EMAIL), result({"gravatarEnabled": True}))
    resp = _client(db, fetcher=fetcher).get(_id_url(size=40))
    assert resp.status_code == 200
    assert resp.content == PNG
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "private, max-age=86400"
    assert resp.headers["etag"] == IMAGE.etag
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "vary" not in resp.headers
    # 40 px rounds up to the 64 px bucket.
    assert fetcher.calls == [(DIGEST, 64)]


def test_response_leaks_neither_the_email_nor_its_hash() -> None:
    db = fake_session(result(EMAIL), result())
    resp = _client(db).get(_id_url())
    blob = (str(dict(resp.headers)) + resp.content.decode("latin-1")).lower()
    assert DIGEST not in blob
    assert hashlib.md5(EMAIL.lower().encode()).hexdigest() not in blob  # noqa: S324
    assert EMAIL.lower() not in blob


@pytest.mark.parametrize(
    "header",
    [IMAGE.etag, f"W/{IMAGE.etag}", f'"other", {IMAGE.etag}', "*"],
)
def test_matching_etag_gives_304(header: str) -> None:
    db = fake_session(result(EMAIL), result())
    resp = _client(db).get(_id_url(), headers={"If-None-Match": header})
    assert resp.status_code == 304
    assert resp.content == b""
    assert resp.headers["etag"] == IMAGE.etag


def test_other_etag_gives_the_image() -> None:
    db = fake_session(result(EMAIL), result())
    resp = _client(db).get(_id_url(), headers={"If-None-Match": '"stale"'})
    assert resp.status_code == 200 and resp.content == PNG


def test_missing_gravatar_is_a_cacheable_problem_404() -> None:
    db = fake_session(result(EMAIL), result())
    resp = _client(db, fetcher=_Fetcher(FetchResult("missing"))).get(_id_url())
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "avatar_not_found"
    assert resp.headers["cache-control"] == "private, max-age=3600"


def test_unknown_principal_or_no_email_is_404_without_a_fetch() -> None:
    fetcher = _Fetcher(FetchResult("found", IMAGE))
    resp = _client(fake_session(result(), result()), fetcher=fetcher).get(_id_url())
    assert resp.status_code == 404
    assert fetcher.calls == []


def test_switched_off_proxy_is_404_without_a_fetch() -> None:
    fetcher = _Fetcher(FetchResult("found", IMAGE))
    db = fake_session(result(EMAIL), result({"gravatarEnabled": False}))
    resp = _client(db, fetcher=fetcher).get(_id_url())
    assert resp.status_code == 404
    assert resp.headers["cache-control"] == "private, max-age=300"
    assert fetcher.calls == []


def test_cache_serves_the_second_request() -> None:
    cache = _Cache()
    fetcher = _Fetcher(FetchResult("found", IMAGE))
    db = fake_session(result(EMAIL), result(), result(EMAIL), result())
    client = _client(db, fetcher=fetcher, cache=cache)
    assert client.get(_id_url()).status_code == 200
    assert client.get(_id_url()).status_code == 200
    assert len(fetcher.calls) == 1


def test_own_avatar_varies_on_the_credentials() -> None:
    fetcher = _Fetcher(FetchResult("found", IMAGE))
    db = fake_session(result(EMAIL), result())
    resp = _client(db, fetcher=fetcher).get("/api/principals/me/avatar?s=256")
    assert resp.status_code == 200
    assert resp.headers["vary"] == "Cookie, Authorization"
    assert fetcher.calls == [(DIGEST, 256)]


def test_own_avatar_404_varies_too() -> None:
    resp = _client(fake_session(result(), result())).get("/api/principals/me/avatar")
    assert resp.status_code == 404
    assert resp.headers["vary"] == "Cookie, Authorization"


@pytest.mark.parametrize("url", ["/api/principals/me/avatar", _id_url()])
def test_requires_a_logged_in_principal(url: str) -> None:
    resp = _client(fake_session(), principal=None).get(url)
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("size", [0, 513])
def test_size_out_of_range_is_422(size: int) -> None:
    resp = _client(fake_session()).get(_id_url(size=size))
    assert resp.status_code == 422


def test_bad_id_is_422() -> None:
    resp = _client(fake_session()).get("/api/principals/not-a-uuid/avatar")
    assert resp.status_code == 422


def test_rate_limit_per_principal() -> None:
    limiter = InMemoryRateLimiter()
    db = fake_session(*[result(EMAIL) if i % 2 == 0 else result() for i in range(8)])
    client = _client(db, limiter=limiter)
    codes = [client.get(_id_url()).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    blocked = client.get(_id_url())
    assert blocked.headers["retry-after"]
    assert blocked.json()["code"] == "rate_limited"
    # Another principal has its own budget.
    other = _client(
        fake_session(result(EMAIL), result()),
        Principal(sub="u2"),
        limiter=limiter,
    )
    assert other.get(_id_url()).status_code == 200


def test_avatar_cache_dependency_is_built_once_per_app() -> None:
    state = SimpleNamespace(_antiabuse_redis=object())
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    first = get_avatar_cache(request, SETTINGS)  # type: ignore[arg-type]
    assert isinstance(first, RedisAvatarCache)
    assert get_avatar_cache(request, SETTINGS) is first  # type: ignore[arg-type]


def test_fetcher_dependency_uses_the_timeout_setting() -> None:
    fetcher = get_gravatar_fetcher(SETTINGS)
    assert isinstance(fetcher, HttpGravatarFetcher)
    assert fetcher._timeout == SETTINGS.gravatar_timeout_seconds


def test_openapi_documents_the_image_and_the_problems() -> None:
    spec = create_app(SETTINGS).openapi()
    op = spec["paths"]["/api/principals/{principal_id}/avatar"]["get"]
    assert "image/png" in op["responses"]["200"]["content"]
    for code in ("401", "404", "429"):
        assert list(op["responses"][code]["content"]) == ["application/problem+json"]
    assert "/api/principals/me/avatar" in spec["paths"]
