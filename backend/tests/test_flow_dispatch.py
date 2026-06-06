"""TDD: Flow-Action-Dispatch (T-14, flows §9.3 Schritt 4)."""

from __future__ import annotations

import logging
from uuid import uuid4

from app.modules.flow.dispatch import (
    ActionDispatcher,
    DispatchedAction,
    NullActionDispatcher,
    build_dispatched_actions,
)


def test_build_skips_set_edit_lock_and_strips_type() -> None:
    app_id, transition_id, event_id = uuid4(), uuid4(), uuid4()
    actions = [
        {"type": "notify", "group": "gremium", "template": "submitted"},
        {"type": "setEditLock", "locked": True},  # inline → nicht dispatcht
        {"type": "webhook", "url": "https://example.org/hook"},
    ]
    dispatched = build_dispatched_actions(
        actions,
        application_id=app_id,
        transition_id=transition_id,
        status_event_id=event_id,
    )
    assert [a.type for a in dispatched] == ["notify", "webhook"]
    notify = dispatched[0]
    assert notify.params == {"group": "gremium", "template": "submitted"}
    # idempotency_key trägt den ORIGINAL-Index (notify=0), nicht den gefilterten.
    assert notify.idempotency_key == f"{app_id}:{event_id}:0:notify"
    assert dispatched[1].idempotency_key == f"{app_id}:{event_id}:2:webhook"


def test_build_empty_actions() -> None:
    assert build_dispatched_actions(
        [], application_id=uuid4(), transition_id=uuid4(), status_event_id=uuid4()
    ) == []


def test_build_only_inline_action_yields_nothing() -> None:
    dispatched = build_dispatched_actions(
        [{"type": "setEditLock", "locked": False}],
        application_id=uuid4(),
        transition_id=uuid4(),
        status_event_id=uuid4(),
    )
    assert dispatched == []


async def test_null_dispatcher_logs_each_action(caplog) -> None:  # noqa: ANN001
    dispatcher = NullActionDispatcher()
    assert isinstance(dispatcher, ActionDispatcher)  # runtime_checkable Protocol
    action = DispatchedAction(
        type="notify",
        application_id=uuid4(),
        transition_id=uuid4(),
        status_event_id=uuid4(),
        idempotency_key="k",
    )
    with caplog.at_level(logging.INFO, logger="app.flow.dispatch"):
        await dispatcher.dispatch([action])
    assert "flow action dispatched" in caplog.text
    assert "type=notify" in caplog.text


async def test_null_dispatcher_empty_is_noop(caplog) -> None:  # noqa: ANN001
    with caplog.at_level(logging.INFO, logger="app.flow.dispatch"):
        await NullActionDispatcher().dispatch([])
    assert caplog.text == ""
