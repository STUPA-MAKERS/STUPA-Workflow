"""Pub/Sub-Fan-out für den Live-Vote-Kanal (api.md §4, flows §5).

Eine Nachricht, die eine App-Instanz auf ``meeting:{id}`` veröffentlicht, muss alle
verbundenen Clients **über alle Instanzen hinweg** erreichen — daher Redis-PubSub.

* :class:`RedisBroker` — Produktion: ``PUBLISH`` + ``SUBSCRIBE`` über ``redis.asyncio``.
* :class:`InMemoryBroker` — Tests/Single-Prozess: ein gemeinsamer :class:`_Hub` (Default
  pro Broker eigener Hub = eine Instanz). Mehrere Broker, die **denselben** Hub teilen,
  simulieren mehrere App-Instanzen an einem Redis → deckt den Fan-out-Test ab.

Beide liefern :meth:`subscribe` als async Context-Manager, der einen async Iterator
über eingehende Nachrichten-Dicts ergibt; das Schließen räumt das Abo sauber ab.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol


class Subscription(Protocol):
    """Async Iterator über eingehende Nachrichten (Dicts) eines Kanals."""

    def __aiter__(self) -> AsyncIterator[dict[str, object]]: ...


class MeetingBroker(Protocol):
    """Pub/Sub-Abstraktion für den Kanal ``meeting:{id}``."""

    async def publish(self, channel: str, message: dict[str, object]) -> None: ...

    def subscribe(self, channel: str) -> AbstractAsyncContextManager[Subscription]: ...


# --------------------------------------------------------------------------- #
# In-Memory (Tests / Single-Prozess)
# --------------------------------------------------------------------------- #
class _Hub:
    """Geteiltes Routing-Backend: Kanal → Menge von Abonnenten-Queues."""

    def __init__(self) -> None:
        self._channels: dict[str, set[asyncio.Queue[dict[str, object]]]] = {}

    def register(self, channel: str) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._channels.setdefault(channel, set()).add(queue)
        return queue

    def unregister(self, channel: str, queue: asyncio.Queue[dict[str, object]]) -> None:
        subs = self._channels.get(channel)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                del self._channels[channel]

    def fan_out(self, channel: str, message: dict[str, object]) -> None:
        for queue in set(self._channels.get(channel, ())):
            queue.put_nowait(message)


class _QueueSubscription:
    def __init__(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._queue = queue

    async def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        while True:
            yield await self._queue.get()


class InMemoryBroker:
    """Prozess-lokaler Broker. ``hub`` teilen ⇒ mehrere Instanzen simulieren."""

    def __init__(self, hub: _Hub | None = None) -> None:
        self._hub = hub or _Hub()

    async def publish(self, channel: str, message: dict[str, object]) -> None:
        self._hub.fan_out(channel, message)

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[_QueueSubscription]:
        queue = self._hub.register(channel)
        try:
            yield _QueueSubscription(queue)
        finally:
            self._hub.unregister(channel, queue)


# --------------------------------------------------------------------------- #
# Redis (Produktion)
# --------------------------------------------------------------------------- #
class _RedisSubscription:
    def __init__(self, pubsub: object) -> None:
        self._pubsub = pubsub

    async def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        async for raw in self._pubsub.listen():  # type: ignore[attr-defined]
            if raw.get("type") != "message":
                continue
            data = raw.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            yield json.loads(data)


class RedisBroker:
    """``redis.asyncio``-gestützter PubSub-Broker (Fan-out über Instanzen)."""

    def __init__(self, client: object) -> None:
        self._client = client

    async def publish(self, channel: str, message: dict[str, object]) -> None:
        await self._client.publish(channel, json.dumps(message))  # type: ignore[attr-defined]

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[_RedisSubscription]:
        pubsub = self._client.pubsub()  # type: ignore[attr-defined]
        await pubsub.subscribe(channel)
        try:
            yield _RedisSubscription(pubsub)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
