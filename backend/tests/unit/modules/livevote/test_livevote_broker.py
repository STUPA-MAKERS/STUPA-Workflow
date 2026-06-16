"""Broker-Fan-out (T-16, api.md §4): PubSub über simulierte Instanzen.

Der In-Memory-Broker mit **geteiltem** Hub modelliert mehrere App-Instanzen an einem
Redis: eine Nachricht, die Instanz A publiziert, muss alle Abonnenten — auch die von
Instanz B — erreichen. Zusätzlich wird die Redis-Implementierung gegen einen
Fake-Client auf Protokoll-Treue geprüft.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.modules.livevote.broker import InMemoryBroker, RedisBroker, _Hub


async def _first(subscription: object) -> dict[str, object]:
    async for message in subscription:  # type: ignore[attr-defined]
        return message
    raise AssertionError("no message")  # pragma: no cover


@pytest.mark.asyncio
async def test_inmemory_fanout_across_two_instances() -> None:
    hub = _Hub()
    instance_a = InMemoryBroker(hub)
    instance_b = InMemoryBroker(hub)

    async with instance_a.subscribe("meeting:1") as sub_a, instance_b.subscribe(
        "meeting:1"
    ) as sub_b:
        await instance_a.publish("meeting:1", {"type": "vote_tally", "n": 1})
        a = await asyncio.wait_for(_first(sub_a), timeout=1)
        b = await asyncio.wait_for(_first(sub_b), timeout=1)
    assert a == b == {"type": "vote_tally", "n": 1}


@pytest.mark.asyncio
async def test_inmemory_isolates_channels() -> None:
    broker = InMemoryBroker()
    async with broker.subscribe("meeting:other") as sub:
        await broker.publish("meeting:unrelated", {"type": "x"})
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(_first(sub), timeout=0.1)


@pytest.mark.asyncio
async def test_unsubscribe_cleans_up_hub() -> None:
    hub = _Hub()
    broker = InMemoryBroker(hub)
    async with broker.subscribe("meeting:1"):
        pass
    # Nach dem Verlassen des Context ist der Kanal abgeräumt (keine Leaks).
    assert "meeting:1" not in hub._channels


# --------------------------------------------------------------------------- #
# Redis-Implementierung gegen Fake-Client (Protokoll-Treue ohne echtes Redis)
# --------------------------------------------------------------------------- #
class _FakePubSub:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self._messages = messages
        self.subscribed: list[str] = []
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def listen(self):  # noqa: ANN201
        # Realistischer Strom: erst ein subscribe-Ack (ignoriert), dann Messages.
        yield {"type": "subscribe", "data": 1}
        for raw in self._messages:
            yield {"type": "message", "data": json.dumps(raw).encode("utf-8")}

    async def unsubscribe(self, channel: str) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


class _FakeRedis:
    def __init__(self, messages: list[dict[str, object]] | None = None) -> None:
        self.published: list[tuple[str, str]] = []
        self._pubsub = _FakePubSub(messages or [])

    async def publish(self, channel: str, data: str) -> None:
        self.published.append((channel, data))

    def pubsub(self) -> _FakePubSub:
        return self._pubsub


@pytest.mark.asyncio
async def test_redis_broker_publish_serialises_json() -> None:
    client = _FakeRedis()
    await RedisBroker(client).publish("meeting:7", {"type": "vote_opened", "voteId": "v"})
    assert client.published == [("meeting:7", '{"type": "vote_opened", "voteId": "v"}')]


@pytest.mark.asyncio
async def test_redis_broker_subscribe_decodes_and_skips_non_messages() -> None:
    client = _FakeRedis(messages=[{"type": "vote_tally", "counts": {"yes": 1}}])
    async with RedisBroker(client).subscribe("meeting:7") as sub:
        msg = await _first(sub)
    assert msg == {"type": "vote_tally", "counts": {"yes": 1}}
    assert client._pubsub.subscribed == ["meeting:7"]
    assert client._pubsub.closed is True
