"""Unit: the cache of the public calendar feed (spec 000733)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.modules.calendar.public import FEED_TTL_SECONDS, RedisFeedCache
from app.modules.calendar.public_router import get_public_feed_cache
from app.settings import Settings


class _Redis:
    """A Redis client in memory. ``broken`` makes every call fail."""

    def __init__(self, *, broken: bool = False) -> None:
        self.broken = broken
        self.values: dict[str, Any] = {}
        self.ttls: list[int] = []

    async def get(self, key: str) -> Any:
        if self.broken:
            raise ConnectionError("down")
        return self.values.get(key)

    async def set(self, key: str, value: Any, *, ex: int) -> None:
        if self.broken:
            raise ConnectionError("down")
        self.values[key] = value
        self.ttls.append(ex)


async def test_feed_cache_keeps_the_bytes_for_five_minutes() -> None:
    client = _Redis()
    cache = RedisFeedCache(client)
    assert await cache.get() is None
    await cache.put(b"BEGIN:VCALENDAR")
    assert await cache.get() == b"BEGIN:VCALENDAR"
    assert client.ttls == [FEED_TTL_SECONDS] == [300]


async def test_feed_cache_ignores_a_value_that_is_no_bytes() -> None:
    client = _Redis()
    cache = RedisFeedCache(client)
    await cache.put(b"x")
    client.values = dict.fromkeys(client.values, "text")
    assert await cache.get() is None


async def test_feed_cache_fails_open() -> None:
    cache = RedisFeedCache(_Redis(broken=True))
    assert await cache.get() is None
    await cache.put(b"x")


def test_the_route_builds_the_redis_cache_of_the_app() -> None:
    client = _Redis()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(_antiabuse_redis=client)))
    cache = get_public_feed_cache(request, Settings())  # type: ignore[arg-type]
    assert isinstance(cache, RedisFeedCache)
