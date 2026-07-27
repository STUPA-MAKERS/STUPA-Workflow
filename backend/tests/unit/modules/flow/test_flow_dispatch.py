"""Unit tests for the flow action dispatch (T-14, flows §9.3 step 4)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.modules.flow import dispatch as dispatch_mod
from app.modules.flow.dispatch import (
    ActionDispatcher,
    DispatchedAction,
    NullActionDispatcher,
    build_dispatched_actions,
    build_implicit_notifications,
)


def test_build_skips_set_edit_lock_and_strips_type() -> None:
    app_id, transition_id, event_id = uuid4(), uuid4(), uuid4()
    actions = [
        {"type": "notify", "group": "gremium", "template": "submitted"},
        {"type": "setEditLock", "locked": True},  # inline action, never dispatched
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
    # The idempotency key holds the original index (notify=0), not the filtered index.
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


class _SpyLogger:
    """Stand-in for the module logger.

    The spy stays deterministic and immune to the global logging config.
    `disable_existing_loggers` or propagation would empty caplog and every handler that
    a test attaches directly.
    """

    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, msg: str, *args: object) -> None:
        self.messages.append(msg % args if args else msg)


async def test_null_dispatcher_logs_each_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = NullActionDispatcher()
    assert isinstance(dispatcher, ActionDispatcher)  # runtime_checkable Protocol
    spy = _SpyLogger()
    monkeypatch.setattr(dispatch_mod, "logger", spy)
    action = DispatchedAction(
        type="notify",
        application_id=uuid4(),
        transition_id=uuid4(),
        status_event_id=uuid4(),
        idempotency_key="k",
    )
    await dispatcher.dispatch([action])
    assert any("flow action dispatched" in m for m in spy.messages)
    assert any("type=notify" in m for m in spy.messages)


async def test_null_dispatcher_empty_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _SpyLogger()
    monkeypatch.setattr(dispatch_mod, "logger", spy)
    await NullActionDispatcher().dispatch([])
    assert spy.messages == []


# Implicit auto mails per status change (#4-3).
def test_implicit_adds_applicant_notify_and_task() -> None:
    app_id, t_id, e_id = uuid4(), uuid4(), uuid4()
    implicit = build_implicit_notifications(
        [{"type": "webhook", "url": "https://x"}],
        application_id=app_id,
        transition_id=t_id,
        status_event_id=e_id,
    )
    assert [a.type for a in implicit] == ["notify", "taskNotify"]
    notify = implicit[0]
    assert notify.params["recipients"] == [{"kind": "applicant"}]
    assert notify.params["templateKey"] == "status_update"
    assert notify.idempotency_key == f"{app_id}:{e_id}:auto:applicant"
    assert implicit[1].idempotency_key == f"{app_id}:{e_id}:auto:task"


def test_implicit_skips_applicant_when_explicitly_notified() -> None:
    implicit = build_implicit_notifications(
        [{"type": "notify", "recipients": [{"kind": "applicant"}]}],
        application_id=uuid4(),
        transition_id=uuid4(),
        status_event_id=uuid4(),
    )
    assert [a.type for a in implicit] == ["taskNotify"]
