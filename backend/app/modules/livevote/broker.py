"""Pub/sub fan-out for the live-vote channel.

A message published on ``meeting:{id}`` by one app instance must reach all
connected clients across all instances — hence Redis pub/sub.

* :class:`RedisBroker` — production: ``PUBLISH``/``SUBSCRIBE`` via ``redis.asyncio``.
* :class:`InMemoryBroker` — tests/single process; brokers sharing one :class:`_Hub`
  simulate multiple app instances on one Redis.

Both expose :meth:`subscribe` as an async context manager yielding an async
iterator of message dicts; closing tears the subscription down cleanly.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol


class Subscription(Protocol):
    """Async iterator over a channel's incoming message dicts."""

    def __aiter__(self) -> AsyncIterator[dict[str, object]]: ...


class MeetingBroker(Protocol):
    """Pub/sub abstraction for the ``meeting:{id}`` channel."""

    async def publish(self, channel: str, message: dict[str, object]) -> None: ...

    def subscribe(self, channel: str) -> AbstractAsyncContextManager[Subscription]: ...


class _Hub:
    """Shared routing backend: channel → set of subscriber queues."""

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
    """Process-local broker; share ``hub`` to simulate multiple instances."""

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
    """``redis.asyncio``-backed pub/sub broker (fan-out across instances)."""

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
