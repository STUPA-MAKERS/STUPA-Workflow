"""Pub/sub fan-out for the live-vote channel.

One app instance publishes a message on `meeting:{id}`. The message must reach
the connected clients of every instance. Redis pub/sub does that fan-out.

`RedisBroker` runs in production. It uses `PUBLISH` and `SUBSCRIBE` of
`redis.asyncio`. `InMemoryBroker` serves the tests and a single process.
Brokers that share one `_Hub` simulate several app instances on one Redis.

Both brokers expose `subscribe` as an async context manager. It yields an async
iterator of message dicts. The exit of the context tears the subscription down.
`subscribe_pattern` does the same for every channel whose name matches a glob
pattern (Redis `PSUBSCRIBE`). The to-do socket uses it for `todo-board:*`: one
subscription per socket instead of one per board, and the socket filters the
boards itself.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from fnmatch import fnmatchcase
from typing import Protocol


class Subscription(Protocol):
    """Async iterator over a channel's incoming message dicts."""

    def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        """Iterate over the incoming messages."""
        ...


class MeetingBroker(Protocol):
    """Pub/sub abstraction for the `meeting:{id}` channel."""

    async def publish(self, channel: str, message: dict[str, object]) -> None:
        """Send a message to every subscriber of the channel."""
        ...

    def subscribe(self, channel: str) -> AbstractAsyncContextManager[Subscription]:
        """Subscribe to one channel for the duration of the block."""
        ...


class PatternBroker(MeetingBroker, Protocol):
    """A broker that also subscribes to every channel that matches a glob pattern."""

    def subscribe_pattern(self, pattern: str) -> AbstractAsyncContextManager[Subscription]:
        """Subscribe to every channel that matches a glob pattern for the block."""
        ...


class _Hub:
    """Shared routing backend that maps a channel to its subscriber queues."""

    def __init__(self) -> None:
        self._channels: dict[str, set[asyncio.Queue[dict[str, object]]]] = {}
        self._patterns: dict[str, set[asyncio.Queue[dict[str, object]]]] = {}

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

    def register_pattern(self, pattern: str) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._patterns.setdefault(pattern, set()).add(queue)
        return queue

    def unregister_pattern(self, pattern: str, queue: asyncio.Queue[dict[str, object]]) -> None:
        subs = self._patterns.get(pattern)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                del self._patterns[pattern]

    def fan_out(self, channel: str, message: dict[str, object]) -> None:
        for queue in set(self._channels.get(channel, ())):
            queue.put_nowait(message)
        for pattern, queues in list(self._patterns.items()):
            if fnmatchcase(channel, pattern):
                for queue in set(queues):
                    queue.put_nowait(message)


class _QueueSubscription:
    def __init__(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._queue = queue

    async def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        while True:
            yield await self._queue.get()


class InMemoryBroker:
    """Process-local broker.

    Share one `hub` between brokers to simulate several app instances.
    """

    def __init__(self, hub: _Hub | None = None) -> None:
        """Use the given hub, or a new one."""
        self._hub = hub or _Hub()

    async def publish(self, channel: str, message: dict[str, object]) -> None:
        """Send a message to every subscriber of the channel."""
        self._hub.fan_out(channel, message)

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[_QueueSubscription]:
        """Subscribe to one channel for the duration of the block."""
        queue = self._hub.register(channel)
        try:
            yield _QueueSubscription(queue)
        finally:
            self._hub.unregister(channel, queue)

    @asynccontextmanager
    async def subscribe_pattern(self, pattern: str) -> AsyncIterator[_QueueSubscription]:
        """Subscribe to every channel that matches a glob pattern for the block."""
        queue = self._hub.register_pattern(pattern)
        try:
            yield _QueueSubscription(queue)
        finally:
            self._hub.unregister_pattern(pattern, queue)


class _RedisSubscription:
    def __init__(self, pubsub: object, kind: str = "message") -> None:
        """Store the subscription and its kind.

        `kind` is `message` for SUBSCRIBE and `pmessage` for PSUBSCRIBE.
        """
        self._pubsub = pubsub
        self._kind = kind

    async def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        async for raw in self._pubsub.listen():  # type: ignore[attr-defined]
            if raw.get("type") != self._kind:
                continue
            data = raw.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            yield json.loads(data)


class RedisBroker:
    """Pub/sub broker on `redis.asyncio` that fans out across app instances."""

    def __init__(self, client: object) -> None:
        """Wrap a `redis.asyncio` client."""
        self._client = client

    async def publish(self, channel: str, message: dict[str, object]) -> None:
        """Publish a message as JSON on the channel."""
        await self._client.publish(channel, json.dumps(message))  # type: ignore[attr-defined]

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[_RedisSubscription]:
        """Subscribe to one channel for the duration of the block."""
        pubsub = self._client.pubsub()  # type: ignore[attr-defined]
        await pubsub.subscribe(channel)
        try:
            yield _RedisSubscription(pubsub)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    @asynccontextmanager
    async def subscribe_pattern(self, pattern: str) -> AsyncIterator[_RedisSubscription]:
        """Subscribe to every channel that matches a glob pattern for the block."""
        pubsub = self._client.pubsub()  # type: ignore[attr-defined]
        await pubsub.psubscribe(pattern)
        try:
            yield _RedisSubscription(pubsub, "pmessage")
        finally:
            await pubsub.punsubscribe(pattern)
            await pubsub.aclose()
