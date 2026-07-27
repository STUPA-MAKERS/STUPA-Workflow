"""Sliding-window rate limiting, keyed per IP or mail address, with configurable limits.

Backends:
- `NullRateLimiter` always allows the request. Rate limiting is off.
- `InMemoryRateLimiter` keeps the window in the process. Use it for tests and for
  single-worker development. It takes an injected `now`.
- `RedisRateLimiter` keeps the window in a sorted set (ZSET) that all workers share. It
  fails open: if Redis is unreachable, it allows the request and logs the error. That
  puts availability over throttling.

The Redis backend uses no `EVAL` and no Lua, and the module never calls Python `eval`. A
pipeline gives enough atomicity.
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
    """Disabled rate limiter that allows every request."""

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        return RateLimitResult(allowed=True, retry_after=0)


class InMemoryRateLimiter:
    """In-process sliding window.

    Use it for tests and for development. Workers do not share the window.
    """

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
    """Sliding window over a Redis ZSET, where the score is the timestamp.

    The limiter fails open. If Redis is unreachable, it allows the request.
    """

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
        # A unique member from a uuid prevents a collision between workers that share
        # the same ZSET key.
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
                # Remove our own entry, so a blocked attempt does not count.
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
