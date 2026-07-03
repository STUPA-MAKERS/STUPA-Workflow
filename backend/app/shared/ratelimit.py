"""Sliding-window rate limiting, keyed per IP/mail with configurable limits.

Backends:
- ``NullRateLimiter``: always allows (rate limiting off).
- ``InMemoryRateLimiter``: process-local (tests/single-worker dev), injectable ``now``.
- ``RedisRateLimiter``: sliding window over a sorted set (ZSET), shared across workers.
  Fail-open: if Redis is unreachable the request is allowed (availability over
  throttling) and the error is logged.

No Redis ``EVAL``/Lua and no Python ``eval``: atomic enough via a pipeline.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import uuid4

logger = logging.getLogger("app.ratelimit")


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int  # Seconds until the next allowed attempt (0 when allowed).


@runtime_checkable
class RateLimiter(Protocol):
    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult: ...


def _wall_clock() -> float:
    import time

    return time.time()


class NullRateLimiter:
    """Rate limiting disabled — every request allowed."""

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        return RateLimitResult(allowed=True, retry_after=0)


class InMemoryRateLimiter:
    """In-process sliding window. For tests/dev; not shared across workers."""

    def __init__(self, *, now: Callable[[], float] | None = None) -> None:
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)
        self._now = now or _wall_clock

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        now = self._now()
        window_start = now - window_seconds
        bucket = self._hits[key]
        while bucket and bucket[0] <= window_start:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = (
                math.ceil(bucket[0] + window_seconds - now) if bucket else window_seconds
            )
            return RateLimitResult(allowed=False, retry_after=max(1, retry_after))
        bucket.append(now)
        return RateLimitResult(allowed=True, retry_after=0)


class RedisRateLimiter:
    """Sliding window over a Redis ZSET (score = timestamp). Fail-open."""

    def __init__(
        self,
        client: object,
        *,
        prefix: str = "rl:",
        now: Callable[[], float] | None = None,
    ) -> None:
        self._client = client
        self._prefix = prefix
        self._now = now or _wall_clock

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        now = self._now()
        window_start = now - window_seconds
        redis_key = f"{self._prefix}{key}"
        # Unique member (uuid): collision-free across workers sharing the same ZSET key.
        member = f"{now}:{uuid4().hex}"
        try:
            pipe = self._client.pipeline()  # type: ignore[attr-defined]
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zadd(redis_key, {member: now})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, window_seconds)
            results = await pipe.execute()
            count = int(results[2])
            if count > limit:
                # Remove our own entry so blocked attempts don't count.
                await self._client.zrem(redis_key, member)  # type: ignore[attr-defined]
                oldest = await self._client.zrange(  # type: ignore[attr-defined]
                    redis_key, 0, 0, withscores=True
                )
                retry_after = (
                    math.ceil(oldest[0][1] + window_seconds - now) if oldest else window_seconds
                )
                return RateLimitResult(allowed=False, retry_after=max(1, retry_after))
            return RateLimitResult(allowed=True, retry_after=0)
        except Exception as exc:  # noqa: BLE001 - fail-open: availability over throttling
            logger.warning("rate-limit backend unavailable, allowing request: %s", exc)
            return RateLimitResult(allowed=True, retry_after=0)
