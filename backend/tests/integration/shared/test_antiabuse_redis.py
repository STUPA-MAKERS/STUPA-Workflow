"""Integration test of the real Redis paths for the rate limiter and the ALTCHA replay guard.

The unit suite checks the logic against a fake. This module runs against a real Redis. It
verifies that the `redis.asyncio` API behaves as expected for the pipeline with a ZSET and
for SET NX EX. See security.md §8 and §7. See also issues #23 and #24. The tests skip
without Docker.
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
    clock["t"] = 1100.0
    assert (await limiter.hit("ip:1", limit=2, window_seconds=60)).allowed


async def test_redis_replay_guard_single_use(redis_client: object) -> None:
    guard = RedisReplayGuard(redis_client)
    assert await guard.seen("sig-abc", ttl_seconds=60) is False
    assert await guard.seen("sig-abc", ttl_seconds=60) is True
