"""Unit tests of the avatar service: kill switch and the cache-then-fetch path."""

from __future__ import annotations

from app.modules.avatars import service
from app.modules.avatars.cache import CachedAvatar
from app.modules.avatars.gravatar import AvatarImage, FetchResult, gravatar_hash
from app.settings import load_settings
from tests._support.auth_fakes import fake_session, result

SETTINGS = load_settings(
    database_url="postgresql+asyncpg://x/y",
    session_secret="session-secret-0123",
    magic_link_secret="magic-link-secret-0",
    gravatar_cache_ttl_seconds=3600,
    gravatar_error_ttl_seconds=60,
)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
IMAGE = AvatarImage(mime="image/png", data=PNG)


class _Cache:
    def __init__(self, entry: CachedAvatar | None = None) -> None:
        self.entry = entry
        self.puts: list[tuple[str, int, AvatarImage | None, int]] = []

    async def get(self, digest: str, size: int) -> CachedAvatar | None:
        return self.entry

    async def put(
        self, digest: str, size: int, image: AvatarImage | None, *, ttl_seconds: int
    ) -> None:
        self.puts.append((digest, size, image, ttl_seconds))


class _Fetcher:
    def __init__(self, result: FetchResult) -> None:
        self.result = result
        self.calls: list[tuple[str, int]] = []

    async def fetch(self, digest: str, size: int) -> FetchResult:
        self.calls.append((digest, size))
        return self.result


async def test_switch_is_on_without_a_config() -> None:
    assert await service.gravatar_enabled(fake_session(result())) is True


async def test_switch_is_on_for_an_older_config_without_the_field() -> None:
    assert await service.gravatar_enabled(fake_session(result({"appName": "X"}))) is True


async def test_switch_follows_the_field() -> None:
    assert await service.gravatar_enabled(fake_session(result({"gravatarEnabled": True})))
    assert not await service.gravatar_enabled(fake_session(result({"gravatarEnabled": False})))


async def test_email_lookups() -> None:
    from uuid import uuid4

    assert await service.email_by_id(fake_session(result("a@x.de")), uuid4()) == "a@x.de"
    assert await service.email_by_sub(fake_session(result()), "s1") is None


async def test_cached_image_skips_the_fetch() -> None:
    fetcher = _Fetcher(FetchResult("found", IMAGE))
    cache = _Cache(CachedAvatar(IMAGE))
    out = await service.load_avatar(
        "a@x.de", 64, cache=cache, fetcher=fetcher, settings=SETTINGS
    )
    assert out == IMAGE
    assert fetcher.calls == []


async def test_cached_miss_skips_the_fetch() -> None:
    fetcher = _Fetcher(FetchResult("found", IMAGE))
    out = await service.load_avatar(
        "a@x.de", 64, cache=_Cache(CachedAvatar(None)), fetcher=fetcher, settings=SETTINGS
    )
    assert out is None
    assert fetcher.calls == []


async def test_found_image_is_cached_for_the_long_ttl() -> None:
    cache = _Cache()
    fetcher = _Fetcher(FetchResult("found", IMAGE))
    out = await service.load_avatar(
        " A@X.de ", 128, cache=cache, fetcher=fetcher, settings=SETTINGS
    )
    assert out == IMAGE
    digest = gravatar_hash("a@x.de")
    assert fetcher.calls == [(digest, 128)]
    assert cache.puts == [(digest, 128, IMAGE, 3600)]


async def test_missing_image_is_cached_for_the_long_ttl() -> None:
    cache = _Cache()
    out = await service.load_avatar(
        "a@x.de", 64, cache=cache, fetcher=_Fetcher(FetchResult("missing")), settings=SETTINGS
    )
    assert out is None
    assert cache.puts[0][2:] == (None, 3600)


async def test_failed_fetch_is_cached_for_the_short_ttl() -> None:
    cache = _Cache()
    out = await service.load_avatar(
        "a@x.de", 64, cache=cache, fetcher=_Fetcher(FetchResult("failed")), settings=SETTINGS
    )
    assert out is None
    assert cache.puts[0][2:] == (None, 60)
