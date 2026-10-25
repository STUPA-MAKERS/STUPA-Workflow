"""Cast lock (``vote:{id}:cast:{sub}``).

The in-memory lock serializes concurrent casts of the same voter. The tests check the
Redis variant against a fake client for ``SET NX PX`` and the release.
"""

from __future__ import annotations

import asyncio

import pytest

from app.modules.livevote.locks import InMemoryLocker, RedisLocker


@pytest.mark.asyncio
async def test_inmemory_lock_serialises_same_key() -> None:
    """Serialize the blocks of the same key in memory.

    The blocks never interleave; each block runs to its end alone.
    """
    locker = InMemoryLocker()
    order: list[str] = []

    async def worker(tag: str) -> None:
        async with locker.acquire("vote:1:cast:alice") as acquired:
            assert acquired is True
            order.append(f"{tag}-in")
            await asyncio.sleep(0.01)
            order.append(f"{tag}-out")

    await asyncio.gather(worker("a"), worker("b"))
    assert order in (["a-in", "a-out", "b-in", "b-out"], ["b-in", "b-out", "a-in", "a-out"])


class _FakeRedis:
    """Stateful fake with ``SET NX PX`` and a token CAS ``EVAL`` like ``_RELEASE_LUA``."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, bool, int]] = []
        self.eval_calls: list[tuple[str, str]] = []

    async def set(self, key: str, value: str, *, nx: bool, px: int):
        self.set_calls.append((key, value, nx, px))
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True

    async def eval(self, _script: str, _numkeys: int, key: str, arg: str) -> int:
        """Delete the key only for the own token, like the Lua compare-and-set."""
        self.eval_calls.append((key, arg))
        if self._store.get(key) == arg:
            del self._store[key]
            return 1
        return 0


@pytest.mark.asyncio
async def test_redis_lock_acquires_with_random_token_and_cas_release() -> None:
    """Take the Redis lock with a random token and release it with a compare-and-set.

    The token is random, not a constant. The release removes the own lock.
    """
    client = _FakeRedis()
    async with RedisLocker(client).acquire("vote:1:cast:bob", ttl_ms=3000) as acquired:
        assert acquired is True
        assert "vote:1:cast:bob" in client._store
    assert client._store == {}
    key, token, nx, px = client.set_calls[0]
    assert (key, nx, px) == ("vote:1:cast:bob", True, 3000)
    assert token != "locked" and len(token) >= 16
    assert client.eval_calls == [("vote:1:cast:bob", token)]


@pytest.mark.asyncio
async def test_redis_lock_contended_yields_false_and_skips_release() -> None:
    """Yield False on a contended lock and skip the release.

    The locker did not get the lock, so it runs no `eval` that touches a foreign lock.
    """
    client = _FakeRedis()
    client._store["vote:1:cast:bob"] = "held-by-other"
    async with RedisLocker(client).acquire("vote:1:cast:bob") as acquired:
        assert acquired is False
    assert client.eval_calls == []
    assert client._store["vote:1:cast:bob"] == "held-by-other"


@pytest.mark.asyncio
async def test_redis_release_does_not_delete_foreign_lock_after_ttl() -> None:
    """A foreign lock survives our release after a TTL expiry.

    The TTL expires and another holder acquires the lock. Our CAS release must NOT
    delete that foreign lock.

    The test simulates the TTL expiry and lets another holder take the lock. The own release
    does not match the foreign token, so the foreign lock stays.
    """
    client = _FakeRedis()
    locker = RedisLocker(client)
    async with locker.acquire("vote:1:cast:bob") as acquired:
        assert acquired is True
        client._store["vote:1:cast:bob"] = "other-holder-token"
    assert client._store["vote:1:cast:bob"] == "other-holder-token"
