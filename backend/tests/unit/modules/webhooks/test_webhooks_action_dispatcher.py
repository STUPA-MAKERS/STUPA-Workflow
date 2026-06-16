"""Flow-Action-Handler `webhook` (T-19)."""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.admin.models import Webhook
from app.modules.flow.dispatch import DispatchedAction
from app.modules.webhooks.action_dispatcher import WebhookActionDispatcher
from app.settings import load_settings
from tests._support.webhooks_fakes import FakeSession, FakeWebhookQueue

SETTINGS = load_settings()


class _SessionCM:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *_a: Any) -> bool:
        return False


def _action(action_type: str, **params: Any) -> DispatchedAction:
    return DispatchedAction(
        type=action_type,
        application_id=uuid.uuid4(),
        transition_id=uuid.uuid4(),
        status_event_id=uuid.uuid4(),
        idempotency_key="app:evt:0:webhook",
        params=params,
    )


def _hook() -> Webhook:
    h = Webhook(
        name="h", url="https://h.test/h", events=["status_changed"],
        active=True, secret=b"k",
    )
    h.id = uuid.uuid4()
    return h


def _disp(session: FakeSession, queue: FakeWebhookQueue) -> WebhookActionDispatcher:
    return WebhookActionDispatcher(
        lambda: _SessionCM(session), queue, SETTINGS  # type: ignore[arg-type]
    )


async def test_ignores_non_webhook_actions() -> None:
    session = FakeSession()
    queue = FakeWebhookQueue()
    await _disp(session, queue).dispatch([_action("notify", event="status_changed")])
    assert queue.enqueued == []
    assert session.added == []


async def test_webhook_action_without_webhook_id_skipped() -> None:
    session = FakeSession()
    queue = FakeWebhookQueue()
    await _disp(session, queue).dispatch([_action("webhook")])
    assert queue.enqueued == []
    assert session.added == []


async def test_webhook_action_invalid_webhook_id_skipped() -> None:
    # webhookId ist keine gültige UUID → ValueError → still übersprungen.
    session = FakeSession()
    queue = FakeWebhookQueue()
    await _disp(session, queue).dispatch([_action("webhook", webhookId="not-a-uuid")])
    assert queue.enqueued == []
    assert session.added == []


async def test_webhook_action_missing_hook_skipped() -> None:
    # webhookId zeigt auf keinen vorhandenen Webhook → still übersprungen.
    session = FakeSession(scalars=[[]])
    queue = FakeWebhookQueue()
    await _disp(session, queue).dispatch(
        [_action("webhook", webhookId=str(uuid.uuid4()))]
    )
    assert queue.enqueued == []
    assert session.added == []


async def test_webhook_action_delivers_to_referenced_hook() -> None:
    hook = _hook()
    session = FakeSession(scalars=[[]])  # _existing_keys → keine Dedup
    session.store[hook.id] = hook
    queue = FakeWebhookQueue()
    action = _action("webhook", webhookId=str(hook.id))
    await _disp(session, queue).dispatch([action])
    assert len(queue.enqueued) == 1
    delivery = session.added[0]
    assert delivery.webhook_id == hook.id
    assert delivery.event == "application.transition"
    assert delivery.payload["event"] == "application.transition"
    assert delivery.payload["applicationId"] == str(action.application_id)
    assert delivery.payload["transitionId"] == str(action.transition_id)
    assert delivery.idempotency_key == "app:evt:0:webhook:" + str(hook.id)


async def test_webhook_action_inactive_hook_skipped() -> None:
    hook = _hook()
    hook.active = False
    session = FakeSession()
    session.store[hook.id] = hook
    queue = FakeWebhookQueue()
    await _disp(session, queue).dispatch([_action("webhook", webhookId=str(hook.id))])
    assert queue.enqueued == []
    assert session.added == []


def test_build_webhook_dispatcher_without_pool() -> None:
    from app.modules.webhooks.action_dispatcher import build_webhook_dispatcher

    disp = build_webhook_dispatcher(None)
    assert disp.queue is None
    assert disp.settings is not None
