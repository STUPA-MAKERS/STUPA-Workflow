"""TDD: Rate-Limiting (sliding window, security.md §8 / api.md §7, Issue #24)."""

from __future__ import annotations

from app.shared.ratelimit import (
    InMemoryRateLimiter,
    NullRateLimiter,
    RedisRateLimiter,
)


async def test_null_limiter_always_allows() -> None:
    limiter = NullRateLimiter()
    for _ in range(100):
        result = await limiter.hit("k", limit=1, window_seconds=60)
        assert result.allowed and result.retry_after == 0


async def test_inmemory_blocks_after_limit() -> None:
    clock = {"t": 0.0}
    limiter = InMemoryRateLimiter(now=lambda: clock["t"])
    assert (await limiter.hit("ip", limit=2, window_seconds=60)).allowed
    assert (await limiter.hit("ip", limit=2, window_seconds=60)).allowed
    blocked = await limiter.hit("ip", limit=2, window_seconds=60)
    assert not blocked.allowed
    assert blocked.retry_after >= 1


async def test_inmemory_window_slides() -> None:
    clock = {"t": 0.0}
    limiter = InMemoryRateLimiter(now=lambda: clock["t"])
    assert (await limiter.hit("ip", limit=1, window_seconds=10)).allowed
    assert not (await limiter.hit("ip", limit=1, window_seconds=10)).allowed
    clock["t"] = 11.0  # alter Treffer aus dem Fenster gefallen
    assert (await limiter.hit("ip", limit=1, window_seconds=10)).allowed


async def test_inmemory_keys_isolated() -> None:
    limiter = InMemoryRateLimiter(now=lambda: 0.0)
    assert (await limiter.hit("a", limit=1, window_seconds=60)).allowed
    # Anderer Key teilt das Budget nicht.
    assert (await limiter.hit("b", limit=1, window_seconds=60)).allowed


# --------------------------------------------------------------------------- #
# Redis-Backend gegen einen In-Memory-ZSET-Fake
# --------------------------------------------------------------------------- #
class _FakePipeline:
    def __init__(self, client: _FakeRedis) -> None:
        self._client = client
        self._ops: list[tuple[object, ...]] = []

    def zremrangebyscore(self, key: str, lo: float, hi: float) -> _FakePipeline:
        self._ops.append(("zrange_rem", key, lo, hi))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> _FakePipeline:
        self._ops.append(("zadd", key, mapping))
        return self

    def zcard(self, key: str) -> _FakePipeline:
        self._ops.append(("zcard", key))
        return self

    def expire(self, key: str, seconds: int) -> _FakePipeline:
        self._ops.append(("expire", key, seconds))
        return self

    async def execute(self) -> list[object]:
        return [self._client._apply(op) for op in self._ops]


class _FakeRedis:
    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.fail = False

    def pipeline(self) -> _FakePipeline:
        if self.fail:
            raise RuntimeError("redis down")
        return _FakePipeline(self)

    def _apply(self, op: tuple[object, ...]) -> object:
        name = op[0]
        if name == "zrange_rem":
            _, key, lo, hi = op
            d = self.zsets.get(key, {})  # type: ignore[index]
            for m in [m for m, s in d.items() if lo <= s <= hi]:
                del d[m]
            return 0
        if name == "zadd":
            _, key, mapping = op
            self.zsets.setdefault(key, {}).update(mapping)  # type: ignore[index,arg-type]
            return len(mapping)  # type: ignore[arg-type]
        if name == "zcard":
            _, key = op
            return len(self.zsets.get(key, {}))  # type: ignore[index]
        return True  # expire

    async def zrem(self, key: str, member: str) -> int:
        self.zsets.get(key, {}).pop(member, None)
        return 1

    async def zrange(self, key: str, lo: int, hi: int, *, withscores: bool = False):
        items = sorted(self.zsets.get(key, {}).items(), key=lambda kv: kv[1])
        sliced = items[lo : (hi + 1) if hi != -1 else None]
        return sliced if withscores else [m for m, _ in sliced]


async def test_redis_limiter_allows_then_blocks() -> None:
    clock = {"t": 1000.0}
    limiter = RedisRateLimiter(_FakeRedis(), now=lambda: clock["t"])
    assert (await limiter.hit("ip", limit=2, window_seconds=60)).allowed
    clock["t"] = 1001.0
    assert (await limiter.hit("ip", limit=2, window_seconds=60)).allowed
    clock["t"] = 1002.0
    blocked = await limiter.hit("ip", limit=2, window_seconds=60)
    assert not blocked.allowed
    assert blocked.retry_after >= 1


async def test_redis_limiter_window_slides() -> None:
    clock = {"t": 0.0}
    limiter = RedisRateLimiter(_FakeRedis(), now=lambda: clock["t"])
    assert (await limiter.hit("ip", limit=1, window_seconds=10)).allowed
    clock["t"] = 5.0
    assert not (await limiter.hit("ip", limit=1, window_seconds=10)).allowed
    clock["t"] = 11.0
    assert (await limiter.hit("ip", limit=1, window_seconds=10)).allowed


async def test_redis_limiter_fail_open() -> None:
    redis = _FakeRedis()
    redis.fail = True
    limiter = RedisRateLimiter(redis, now=lambda: 0.0)
    result = await limiter.hit("ip", limit=1, window_seconds=60)
    assert result.allowed and result.retry_after == 0
