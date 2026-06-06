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
import secrets
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


# Token-sicheres Release: nur löschen, wenn der Lock noch **uns** gehört. Sonst würde
# ein nach TTL-Ablauf erneut vergebener Lock eines anderen Halters fälschlich gelöscht.
# Atomar in Lua (CAS), damit zwischen GET und DEL kein fremder Acquire schlüpfen kann.
_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


class RedisLocker:
    """``SET NX PX``-Lock über ``redis.asyncio`` (Fan-out-sicher).

    Pro Acquire ein **zufälliger** Token; Release per Lua-CAS löscht nur den eigenen
    Lock (verhindert das Freigeben eines bereits abgelaufen-und-neuvergebenen Locks)."""

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
                # CAS-Release; ablaufende TTL deckt den Crash-Fall ab.
                await self._client.eval(_RELEASE_LUA, 1, key, token)  # type: ignore[attr-defined]
