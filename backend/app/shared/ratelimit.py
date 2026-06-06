"""Rate-Limiting (sliding window, security.md §8 / api.md §7, Issue #24).

Schlüssel pro IP/Mail; Limits konfigurierbar. Backends:

- `NullRateLimiter`: immer erlaubt (Rate-Limiting aus).
- `InMemoryRateLimiter`: prozesslokal (Tests/Single-Worker-Dev), `now` injizierbar.
- `RedisRateLimiter`: Sliding-Window über ein Sorted-Set (ZSET) — geteilt über alle
  Worker. **Fail-open**: ist Redis nicht erreichbar, wird der Request durchgelassen
  (Verfügbarkeit vor Drosselung) und der Fehler geloggt.

Kein Redis-`EVAL`/Lua (und kein Python-`eval`): atomar genug via Pipeline.
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
    retry_after: int  # Sekunden bis zum nächsten erlaubten Versuch (0 wenn erlaubt).


@runtime_checkable
class RateLimiter(Protocol):
    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult: ...


def _wall_clock() -> float:
    import time

    return time.time()


class NullRateLimiter:
    """Rate-Limiting deaktiviert — jeder Request erlaubt."""

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        return RateLimitResult(allowed=True, retry_after=0)


class InMemoryRateLimiter:
    """Sliding-Window im Prozess. Für Tests/Dev; nicht über Worker geteilt."""

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
    """Sliding-Window über ein Redis-ZSET (Score = Zeitstempel). Fail-open."""

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
        # Eindeutiges Member (uuid statt Prozess-Counter): kollisionsfrei auch über
        # mehrere Worker/Prozesse, die sich denselben ZSET-Key teilen.
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
                # Eigenen Eintrag zurücknehmen → blockierte Versuche zählen nicht mit.
                await self._client.zrem(redis_key, member)  # type: ignore[attr-defined]
                oldest = await self._client.zrange(  # type: ignore[attr-defined]
                    redis_key, 0, 0, withscores=True
                )
                retry_after = (
                    math.ceil(oldest[0][1] + window_seconds - now) if oldest else window_seconds
                )
                return RateLimitResult(allowed=False, retry_after=max(1, retry_after))
            return RateLimitResult(allowed=True, retry_after=0)
        except Exception as exc:  # noqa: BLE001 — fail-open: Verfügbarkeit vor Drosselung
            logger.warning("rate-limit backend unavailable, allowing request: %s", exc)
            return RateLimitResult(allowed=True, retry_after=0)
