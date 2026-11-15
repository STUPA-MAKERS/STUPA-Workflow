"""The webhook delivery that the code sends matches its protocol spec."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.webhook_actions import WebhookActionDispatcher
from app.modules.webhooks.models import Webhook
from app.modules.webhooks.signing import EVENT_HEADER, build_headers, canonical_body
from app.settings import load_settings
from tests._support.protocols import assert_matches_schema
from tests._support.webhooks_fakes import FakeSession, FakeWebhookQueue


class _SessionCM:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *_a: Any) -> bool:
        return False


async def test_transition_delivery_matches_schema() -> None:
    """A transition delivery matches the schema. §P/integrations/webhooks/000963."""
    hook = Webhook(name="h", url="https://h.test/h", active=True, secret=b"k")
    hook.id = uuid.uuid4()
    session = FakeSession(scalars=[[]])
    session.store[hook.id] = hook
    queue = FakeWebhookQueue()
    action = DispatchedAction(
        type="webhook",
        application_id=uuid.uuid4(),
        transition_id=uuid.uuid4(),
        status_event_id=uuid.uuid4(),
        idempotency_key="app:evt:0:webhook",
        params={"webhookId": str(hook.id)},
    )
    dispatcher = WebhookActionDispatcher(
        lambda: _SessionCM(session),  # type: ignore[arg-type]
        queue,
        load_settings(),
    )
    await dispatcher.dispatch([action])
    delivery = session.added[0]
    body = canonical_body(delivery.payload)
    assert_matches_schema("000963", json.loads(body))
    headers = build_headers(b"k", body, event=delivery.event, timestamp=0)
    assert headers[EVENT_HEADER] == delivery.payload["event"]
