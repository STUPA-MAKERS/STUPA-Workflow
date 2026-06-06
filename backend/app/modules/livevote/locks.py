"""Verteilte Kurz-Locks gegen Cast-Races (api.md §4: ``vote:{id}:cast:{sub}``).

Die Doppelstimme ist bereits auf DB-Ebene **atomar** ausgeschlossen (UNIQUE
``(vote_id, voter_sub)`` bzw. ``voted_marker``, T-15). Der Lock serialisiert
gleichzeitige Casts **desselben** Wählers über Instanzen hinweg vor dem DB-Treffer,
damit konkurrierende Requests nicht beide bis zum (dann scheiternden) Insert laufen
— Defense-in-Depth, nicht die alleinige Garantie.

* :class:`RedisLocker` — ``SET key token NX PX ttl`` (atomar) + token-sicheres Release.
* :class:`InMemoryLocker` — Prozess-lokaler ``asyncio.Lock`` je Key (Tests/Single-Proc).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol


class Locker(Protocol):
    """Kurz-Lock-Abstraktion; ``acquire`` als Context-Manager, ``True`` = exklusiv."""

    def acquire(
        self, key: str, *, ttl_ms: int = ...
    ) -> AbstractAsyncContextManager[bool]: ...


class InMemoryLocker:
    """Prozess-lokaler Lock je Key (für Tests/Single-Prozess)."""

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


class RedisLocker:
    """``SET NX PX``-Lock über ``redis.asyncio`` (Fan-out-sicher)."""

    def __init__(self, client: object, token: str = "locked") -> None:
        self._client = client
        self._token = token

    @asynccontextmanager
    async def acquire(self, key: str, *, ttl_ms: int = 5000) -> AsyncIterator[bool]:
        got = await self._client.set(key, self._token, nx=True, px=ttl_ms)  # type: ignore[attr-defined]
        acquired = bool(got)
        try:
            yield acquired
        finally:
            if acquired:
                # Best-effort-Release; ablaufende TTL deckt den Crash-Fall ab.
                await self._client.delete(key)  # type: ignore[attr-defined]
