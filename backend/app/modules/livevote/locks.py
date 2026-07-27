"""Short-lived distributed locks that guard concurrent cast races.

A UNIQUE constraint in the database already excludes a double vote atomically.
This lock only serializes the concurrent casts of one voter across app
instances before they reach the database. It is defense in depth and not the
only guarantee.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol


class Locker(Protocol):
    """Abstraction of a short lock.

    `acquire` is an async context manager. It yields `True` when the caller
    holds the lock exclusively.
    """

    def acquire(
        self, key: str, *, ttl_ms: int = ...
    ) -> AbstractAsyncContextManager[bool]: ...


class InMemoryLocker:
    """Process-local lock per key for the tests and a single process."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def acquire(self, key: str, *, ttl_ms: int = 5000) -> AsyncIterator[bool]:
        lock = self._locks.setdefault(key, asyncio.Lock())
        await lock.acquire()
        try:
            yield True
        finally:
            lock.release()


# Token-safe release. Delete the key only while the lock still belongs to this
# holder. A lock that another holder took after the TTL expired must survive.
# The Lua compare-and-set is atomic, so no foreign `acquire` slips between GET
# and DEL.
_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


class RedisLocker:
    """Lock with `SET NX PX` over `redis.asyncio`, safe across app instances.

    Every `acquire` uses a random token. The Lua compare-and-set release deletes
    the own lock only. It never deletes a lock that expired and that another
    holder took.
    """

    def __init__(self, client: object) -> None:
        self._client = client

    @asynccontextmanager
    async def acquire(self, key: str, *, ttl_ms: int = 5000) -> AsyncIterator[bool]:
        token = secrets.token_hex(16)
        got = await self._client.set(key, token, nx=True, px=ttl_ms)  # type: ignore[attr-defined]
        acquired = bool(got)
        try:
            yield acquired
        finally:
            if acquired:
                # Compare-and-set release. An expiring TTL covers the crash case.
                await self._client.eval(_RELEASE_LUA, 1, key, token)  # type: ignore[attr-defined]
