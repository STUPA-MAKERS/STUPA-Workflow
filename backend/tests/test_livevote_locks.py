"""Cast-Lock (T-16, api.md §4: ``vote:{id}:cast:{sub}``).

Der In-Memory-Lock serialisiert konkurrierende Casts desselben Wählers; die
Redis-Variante wird gegen einen Fake-Client auf ``SET NX PX`` + Release geprüft.
"""

from __future__ import annotations

import asyncio

import pytest

from app.modules.livevote.locks import InMemoryLocker, RedisLocker


@pytest.mark.asyncio
async def test_inmemory_lock_serialises_same_key() -> None:
    locker = InMemoryLocker()
    order: list[str] = []

    async def worker(tag: str) -> None:
        async with locker.acquire("vote:1:cast:alice") as acquired:
            assert acquired is True
            order.append(f"{tag}-in")
            await asyncio.sleep(0.01)
            order.append(f"{tag}-out")

    await asyncio.gather(worker("a"), worker("b"))
    # Keine Verschränkung: jeder Block läuft exklusiv zu Ende.
    assert order in (["a-in", "a-out", "b-in", "b-out"], ["b-in", "b-out", "a-in", "a-out"])


class _FakeRedis:
    def __init__(self, *, free: bool = True) -> None:
        self._free = free
        self.set_calls: list[tuple[str, str, bool, int]] = []
        self.deleted: list[str] = []

    async def set(self, key: str, value: str, *, nx: bool, px: int):  # noqa: ANN201
        self.set_calls.append((key, value, nx, px))
        return True if self._free else None

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


@pytest.mark.asyncio
async def test_redis_lock_acquires_with_nx_px_and_releases() -> None:
    client = _FakeRedis(free=True)
    async with RedisLocker(client).acquire("vote:1:cast:bob", ttl_ms=3000) as acquired:
        assert acquired is True
    assert client.set_calls == [("vote:1:cast:bob", "locked", True, 3000)]
    assert client.deleted == ["vote:1:cast:bob"]


@pytest.mark.asyncio
async def test_redis_lock_contended_does_not_release_foreign_lock() -> None:
    client = _FakeRedis(free=False)
    async with RedisLocker(client).acquire("vote:1:cast:bob") as acquired:
        assert acquired is False
    # Nicht erworben → kein delete (würde sonst fremden Lock freigeben).
    assert client.deleted == []
