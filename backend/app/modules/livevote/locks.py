"""Distributed short-lived locks guarding concurrent cast races.

Double-votes are already excluded atomically at the DB level (UNIQUE
constraint); this lock only serializes concurrent casts of the same voter across
instances before the DB hit — defense-in-depth, not the sole guarantee.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol


class Locker(Protocol):
    """Short-lock abstraction; ``acquire`` is a context manager yielding ``True`` when exclusive."""

    def acquire(
        self, key: str, *, ttl_ms: int = ...
    ) -> AbstractAsyncContextManager[bool]: ...


class InMemoryLocker:
    """Process-local lock per key (tests/single-process)."""

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


# Token-safe release: delete only while the lock is still ours, so a lock
# re-acquired by another holder after TTL expiry isn't deleted. Atomic Lua CAS so
# no foreign acquire slips between GET and DEL.
_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


class RedisLocker:
    """``SET NX PX`` lock over ``redis.asyncio`` (fan-out safe).

    Each acquire uses a random token; the Lua-CAS release deletes only our own
    lock, never one that already expired and was re-acquired.
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
                # CAS release; an expiring TTL covers the crash case.
                await self._client.eval(_RELEASE_LUA, 1, key, token)  # type: ignore[attr-defined]
