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
    """Stateful Fake: ``SET NX PX`` + token-CAS ``EVAL`` (wie ``_RELEASE_LUA``)."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, bool, int]] = []
        self.eval_calls: list[tuple[str, str]] = []

    async def set(self, key: str, value: str, *, nx: bool, px: int):  # noqa: ANN201
        self.set_calls.append((key, value, nx, px))
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True

    async def eval(self, _script: str, _numkeys: int, key: str, arg: str) -> int:  # noqa: ANN001
        self.eval_calls.append((key, arg))
        if self._store.get(key) == arg:  # CAS: nur eigenen Lock löschen
            del self._store[key]
            return 1
        return 0


@pytest.mark.asyncio
async def test_redis_lock_acquires_with_random_token_and_cas_release() -> None:
    client = _FakeRedis()
    async with RedisLocker(client).acquire("vote:1:cast:bob", ttl_ms=3000) as acquired:
        assert acquired is True
        # gehalten → Schlüssel belegt
        assert "vote:1:cast:bob" in client._store
    # Release per CAS hat den eigenen Lock entfernt.
    assert client._store == {}
    key, token, nx, px = client.set_calls[0]
    assert (key, nx, px) == ("vote:1:cast:bob", True, 3000)
    assert token != "locked" and len(token) >= 16  # zufälliger Token, kein Konstant-Wert
    assert client.eval_calls == [("vote:1:cast:bob", token)]


@pytest.mark.asyncio
async def test_redis_lock_contended_yields_false_and_skips_release() -> None:
    client = _FakeRedis()
    client._store["vote:1:cast:bob"] = "held-by-other"
    async with RedisLocker(client).acquire("vote:1:cast:bob") as acquired:
        assert acquired is False
    # Nicht erworben → kein eval (würde sonst fremden Lock anfassen).
    assert client.eval_calls == []
    assert client._store["vote:1:cast:bob"] == "held-by-other"


@pytest.mark.asyncio
async def test_redis_release_does_not_delete_foreign_lock_after_ttl() -> None:
    """TTL-Ablauf + Neuvergabe: unser Release darf den fremden Lock NICHT löschen."""
    client = _FakeRedis()
    locker = RedisLocker(client)
    async with locker.acquire("vote:1:cast:bob") as acquired:
        assert acquired is True
        # Simuliere TTL-Ablauf + Neu-Acquire durch anderen Halter:
        client._store["vote:1:cast:bob"] = "other-holder-token"
    # Unser CAS-Release matcht den fremden Token nicht → fremder Lock bleibt.
    assert client._store["vote:1:cast:bob"] == "other-holder-token"
