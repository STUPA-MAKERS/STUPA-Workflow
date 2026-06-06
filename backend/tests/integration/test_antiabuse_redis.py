"""Integration (Docker/Redis): echte Redis-Pfade von Rate-Limiter + Altcha-Replay.

Die Unit-Suite prüft die Logik gegen einen Fake; hier wird gegen ein echtes Redis
verifiziert, dass die `redis.asyncio`-API (Pipeline/ZSET, SET NX EX) wie erwartet greift
(security.md §8/§7, Issues #23/#24). Skip ohne Docker.
"""

from __future__ import annotations

import pytest

from app.shared.altcha import RedisReplayGuard
from app.shared.ratelimit import RedisRateLimiter

pytestmark = pytest.mark.integration


@pytest.fixture
async def redis_client(redis_url: str):
    import redis.asyncio as aioredis

    client = aioredis.from_url(redis_url)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.aclose()


async def test_redis_rate_limiter_blocks_and_recovers(redis_client: object) -> None:
    clock = {"t": 1000.0}
    limiter = RedisRateLimiter(redis_client, now=lambda: clock["t"])
    assert (await limiter.hit("ip:1", limit=2, window_seconds=60)).allowed
    clock["t"] = 1001.0
    assert (await limiter.hit("ip:1", limit=2, window_seconds=60)).allowed
    clock["t"] = 1002.0
    blocked = await limiter.hit("ip:1", limit=2, window_seconds=60)
    assert not blocked.allowed and blocked.retry_after >= 1
    # Fenster verlassen → wieder erlaubt.
    clock["t"] = 1100.0
    assert (await limiter.hit("ip:1", limit=2, window_seconds=60)).allowed


async def test_redis_replay_guard_single_use(redis_client: object) -> None:
    guard = RedisReplayGuard(redis_client)
    assert await guard.seen("sig-abc", ttl_seconds=60) is False
    assert await guard.seen("sig-abc", ttl_seconds=60) is True
