"""The webhook delivery that the code sends matches its protocol spec."""

from __future__ import annotations

import json
import uuid

import pytest

from app.modules.admin.service.webhooks import build_test_body
from app.modules.webhooks.catalog import EVENTS
from app.modules.webhooks.events import WebhookEvent, emit_event
from app.modules.webhooks.models import Webhook
from app.modules.webhooks.signing import EVENT_HEADER, build_headers, canonical_body
from tests._support.protocols import assert_matches_schema
from tests._support.webhooks_fakes import FakeSession
from tests.unit.conftest import ActiveWebhooks


def _hook(subs: list[dict[str, object]]) -> Webhook:
    hook = Webhook(name="h", url="https://h.test/h", active=True, secret=b"k", subscriptions=subs)
    hook.id = uuid.uuid4()
    return hook


@pytest.mark.parametrize("name", list(EVENTS))
async def test_event_delivery_matches_schema(name: str, active_webhooks: ActiveWebhooks) -> None:
    """Each catalog event with all fields matches the schema. §P/integrations/webhooks/000963."""
    spec = EVENTS[name]
    active_webhooks.hooks = [_hook([{"event": name, "fields": sorted(spec.field_keys)}])]
    session = FakeSession()

    async def fields() -> dict[str, object]:
        return {f.key: f.example for f in spec.fields}

    await emit_event(
        session,  # type: ignore[arg-type]
        WebhookEvent(
            name=spec.name, ids={key: uuid.uuid4() for key in spec.id_keys}, fields=fields
        ),
    )
    delivery = session.added[0]
    body = canonical_body(delivery.payload)
    assert_matches_schema("000963", json.loads(body))
    assert set(delivery.payload["data"]) == spec.field_keys
    headers = build_headers(b"k", body, event=delivery.event, timestamp=0)
    assert headers[EVENT_HEADER] == delivery.payload["event"]


def test_test_delivery_matches_schema() -> None:
    """The test delivery matches the schema. §F/integrations/webhooks/002416."""
    hook = _hook(
        [
            {"event": "application.created", "fields": ["title", "amount"]},
            {"event": "vote.closed", "fields": []},
            {"event": "gone.event", "fields": []},
        ]
    )
    body = build_test_body(hook, "2026-11-23T09:00:00+00:00")
    assert_matches_schema("000963", json.loads(canonical_body(body)))
    assert body["data"] == {
        "application.created": {"title": "Zuschuss Sommerfest", "amount": "125.00"},
        "vote.closed": {},
    }
