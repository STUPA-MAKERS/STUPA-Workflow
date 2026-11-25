"""The event catalog and the fan-out of an event to the subscribed webhooks."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from typing import Any, get_args

import pytest

from app.modules.webhooks import events as events_mod
from app.modules.webhooks.catalog import EVENTS, WebhookEventName, example_payload
from app.modules.webhooks.events import (
    WebhookEvent,
    build_body,
    emit_event,
    has_subscriber,
    subscribed_fields,
)
from app.modules.webhooks.models import Webhook, WebhookDelivery
from tests._support.webhooks_fakes import FakeSession
from tests.unit.conftest import ActiveWebhooks

_AT = dt.datetime(2026, 11, 23, 9, 0, tzinfo=dt.UTC)


def _hook(
    subs: list[dict[str, Any]],
    *,
    gremiums: list[str] | None = None,
    types: list[str] | None = None,
    states: list[str] | None = None,
) -> Webhook:
    hook = Webhook(
        name="h",
        url="https://hook.test/h",
        active=True,
        secret=b"k",
        subscriptions=subs,
        gremium_ids=gremiums or [],
        type_ids=types or [],
        state_keys=states or [],
    )
    hook.id = uuid.uuid4()
    return hook


def test_catalog_matches_the_event_names() -> None:
    """The catalog holds exactly the events of the spec. §F/integrations/webhooks/002411."""
    assert tuple(EVENTS) == get_args(WebhookEventName)
    assert len(EVENTS) == 18
    for spec in EVENTS.values():
        assert spec.id_keys
        assert len(spec.field_keys) == len(spec.fields)


def test_example_payload_holds_only_the_chosen_fields() -> None:
    body = example_payload(EVENTS["application.created"], ["title", "nope"])
    assert body["event"] == "application.created"
    assert body["data"] == {"title": "Zuschuss Sommerfest"}
    assert "applicationId" in body


def test_subscribed_fields() -> None:
    hook = _hook([{"event": "vote.opened"}, {"event": "vote.closed", "fields": ["result"]}])
    assert subscribed_fields(hook, "vote.opened") == []
    assert subscribed_fields(hook, "vote.closed") == ["result"]
    assert subscribed_fields(hook, "meeting.created") is None
    hook.subscriptions = None  # type: ignore[assignment]
    assert subscribed_fields(hook, "vote.opened") is None


def test_build_body_keeps_ids_and_drops_unknown_keys() -> None:
    """The body holds the event, the IDs and the chosen fields. §F/integrations/webhooks/002412."""
    app_id = uuid.uuid4()
    event = WebhookEvent(
        name="application.transition",
        ids={"applicationId": app_id, "transitionId": None},
        occurred_at=_AT,
    )
    body = build_body(event, ["title", "bogus"], {"title": "T", "amount": "1.00"})
    assert body == {
        "event": "application.transition",
        "occurredAt": _AT.isoformat(),
        "applicationId": str(app_id),
        "transitionId": None,
        "data": {"title": "T"},
    }


async def test_has_subscriber(active_webhooks: ActiveWebhooks) -> None:
    """An emit site asks first, so an event without a subscriber reads nothing."""
    active_webhooks.hooks = [_hook([{"event": "vote.opened"}])]
    session = FakeSession()
    assert await has_subscriber(session, "vote.opened")  # type: ignore[arg-type]
    assert not await has_subscriber(session, "vote.closed")  # type: ignore[arg-type]


async def test_emit_without_subscriber_adds_nothing(active_webhooks: ActiveWebhooks) -> None:
    active_webhooks.hooks = [_hook([{"event": "vote.opened", "fields": ["question"]}])]
    session = FakeSession()
    called: list[bool] = []

    async def fields() -> Mapping[str, Any]:
        called.append(True)
        return {}

    n = await emit_event(
        session,  # type: ignore[arg-type]
        WebhookEvent(name="meeting.created", ids={"meetingId": uuid.uuid4()}, fields=fields),
    )
    assert n == 0
    assert session.added == []
    assert called == []


async def test_emit_without_fields_skips_the_read(active_webhooks: ActiveWebhooks) -> None:
    """A subscription without fields sends the IDs and reads no field."""
    active_webhooks.hooks = [_hook([{"event": "meeting.created", "fields": []}])]
    session = FakeSession()

    async def fields() -> Mapping[str, Any]:
        raise AssertionError("must not read the fields")

    n = await emit_event(
        session,  # type: ignore[arg-type]
        WebhookEvent(name="meeting.created", ids={"meetingId": uuid.uuid4()}, fields=fields),
    )
    assert n == 1
    delivery = session.added[0]
    assert isinstance(delivery, WebhookDelivery)
    assert delivery.status == "pending"
    assert delivery.payload["data"] == {}


async def test_emit_one_delivery_per_subscriber(active_webhooks: ActiveWebhooks) -> None:
    """Only the subscribing webhooks get a delivery. §F/integrations/webhooks/002410."""
    first = _hook([{"event": "ticket.created", "fields": ["title"]}])
    second = _hook([{"event": "ticket.created", "fields": ["number", "title"]}])
    other = _hook([{"event": "invoice.created", "fields": []}])
    active_webhooks.hooks = [first, second, other]
    session = FakeSession()
    reads: list[bool] = []

    async def fields() -> Mapping[str, Any]:
        reads.append(True)
        return {"title": "T", "number": "T-0001"}

    n = await emit_event(
        session,  # type: ignore[arg-type]
        WebhookEvent(name="ticket.created", ids={"ticketId": uuid.uuid4()}, fields=fields),
    )
    assert n == 2
    assert reads == [True]
    assert [d.webhook_id for d in session.added] == [first.id, second.id]
    assert session.added[0].payload["data"] == {"title": "T"}
    assert session.added[1].payload["data"] == {"number": "T-0001", "title": "T"}


async def test_emit_default_fields_give_none(active_webhooks: ActiveWebhooks) -> None:
    active_webhooks.hooks = [_hook([{"event": "invoice.created", "fields": ["number"]}])]
    session = FakeSession()
    await emit_event(
        session,  # type: ignore[arg-type]
        WebhookEvent(name="invoice.created", ids={"invoiceId": uuid.uuid4()}),
    )
    assert session.added[0].payload["data"] == {"number": None}


_G1, _G2 = str(uuid.uuid4()), str(uuid.uuid4())


@pytest.mark.parametrize(
    ("hook_filter", "event_kw", "passes"),
    [
        ({}, {"gremium_id": uuid.UUID(_G1)}, True),
        ({"gremiums": [_G1]}, {"gremium_id": uuid.UUID(_G1)}, True),
        ({"gremiums": [_G1]}, {"gremium_id": uuid.UUID(_G2)}, False),
        ({"gremiums": [_G1]}, {}, True),
        ({"types": [_G1]}, {"type_id": uuid.UUID(_G2)}, False),
        ({"types": [_G1]}, {"type_id": uuid.UUID(_G1)}, True),
        ({"states": ["approved"]}, {"state_key": "approved"}, True),
        ({"states": ["approved"]}, {"state_key": "rejected"}, False),
    ],
)
async def test_filters(
    active_webhooks: ActiveWebhooks,
    hook_filter: dict[str, list[str]],
    event_kw: dict[str, Any],
    passes: bool,
) -> None:
    """Gremium, Antragsart and target status filter an event. §F/integrations/webhooks/002414."""
    active_webhooks.hooks = [
        _hook([{"event": "application.transition", "fields": []}], **hook_filter)
    ]
    session = FakeSession()
    n = await emit_event(
        session,  # type: ignore[arg-type]
        WebhookEvent(
            name="application.transition", ids={"applicationId": uuid.uuid4()}, **event_kw
        ),
    )
    assert n == (1 if passes else 0)


async def test_state_filter_applies_only_to_transitions(active_webhooks: ActiveWebhooks) -> None:
    active_webhooks.hooks = [
        _hook([{"event": "application.created", "fields": []}], states=["approved"])
    ]
    session = FakeSession()
    n = await emit_event(
        session,  # type: ignore[arg-type]
        WebhookEvent(
            name="application.created", ids={"applicationId": uuid.uuid4()}, state_key="draft"
        ),
    )
    assert n == 1


@pytest.mark.real_webhooks
async def test_active_webhooks_reads_the_table() -> None:
    hook = _hook([])
    session = FakeSession(scalars=[[hook]])
    assert list(await events_mod.active_webhooks(session)) == [hook]  # type: ignore[arg-type]
