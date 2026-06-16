"""Tests des Flow-Action-Dispatchers `notify` (T-18) — Service gefaked."""

from __future__ import annotations

import uuid
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.flow.dispatch import DispatchedAction
from app.modules.notifications import action_dispatcher as mod
from app.modules.notifications.action_dispatcher import NotificationActionDispatcher
from app.settings import load_settings
from tests._support.notifications_fakes import FakeSession

SETTINGS = load_settings()


def _sessionmaker(session: FakeSession) -> async_sessionmaker[AsyncSession]:
    class _CM:
        async def __aenter__(self) -> FakeSession:
            return session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return cast("async_sessionmaker[AsyncSession]", lambda: _CM())


def _action(action_type: str, params: dict | None = None) -> DispatchedAction:
    app_id = uuid.uuid4()
    return DispatchedAction(
        type=action_type,
        application_id=app_id,
        transition_id=uuid.uuid4(),
        status_event_id=uuid.uuid4(),
        idempotency_key=f"{app_id}:se:0:{action_type}",
        params=params or {},
    )


async def test_dispatch_notify_calls_service(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeService:
        def __init__(self, session, *, queue, settings) -> None:  # noqa: ANN001
            captured["session"] = session

        async def handle_notify_action(self, action, **kw):  # noqa: ANN001, ANN003
            captured["action"] = action
            captured["kw"] = kw
            return 1

    monkeypatch.setattr(mod, "NotificationService", FakeService)
    app_type_id = uuid.uuid4()
    session = FakeSession(executes=[[(app_type_id, None, {"title": "Beamer"})]])
    disp = NotificationActionDispatcher(_sessionmaker(session), None, SETTINGS)

    action = _action("notify", {"event": "status_changed", "lang": "en"})
    await disp.dispatch([action])

    assert captured["action"] == action.params
    kw = captured["kw"]
    assert kw["application_id"] == action.application_id  # type: ignore[index]
    assert kw["application_type_id"] == app_type_id  # type: ignore[index]
    assert kw["idempotency_base"] == action.idempotency_key  # type: ignore[index]
    assert kw["lang"] == "en"  # type: ignore[index]
    assert kw["context"]["applicationId"] == str(action.application_id)  # type: ignore[index]
    assert kw["context"]["applicationTitle"] == "Beamer"  # type: ignore[index]


async def test_dispatch_skips_non_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    class FakeService:
        def __init__(self, *a, **k) -> None:  # noqa: ANN002, ANN003
            called.append(True)

        async def handle_notify_action(self, *a, **k):  # noqa: ANN002, ANN003
            called.append(True)
            return 1

    monkeypatch.setattr(mod, "NotificationService", FakeService)
    disp = NotificationActionDispatcher(_sessionmaker(FakeSession()), None, SETTINGS)
    await disp.dispatch([_action("webhook"), _action("budgetReserve")])
    assert called == []  # Service nie instanziiert/aufgerufen


async def test_dispatch_notify_merges_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeService:
        def __init__(self, *a, **k) -> None:  # noqa: ANN002, ANN003
            pass

        async def handle_notify_action(self, action, **kw):  # noqa: ANN001, ANN003
            captured["kw"] = kw
            return 1

    monkeypatch.setattr(mod, "NotificationService", FakeService)
    session = FakeSession(executes=[[(None, None, None)]])
    disp = NotificationActionDispatcher(_sessionmaker(session), None, SETTINGS)
    action = _action("notify", {"templateKey": "t", "context": {"status": "X"}})
    await disp.dispatch([action])
    ctx = captured["kw"]["context"]  # type: ignore[index]
    assert ctx["status"] == "X"
    assert "applicationId" in ctx


def test_build_notify_dispatcher_uses_settings() -> None:
    disp = mod.build_notify_dispatcher(None)
    assert isinstance(disp, NotificationActionDispatcher)
    assert disp.queue is None


async def test_dispatch_task_notify_sends_kind_mail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`taskNotify` (#4-3): Empfänger zur Versandzeit, Versand via send_kind_mail."""
    captured: dict[str, object] = {}

    class FakeService:
        def __init__(self, session, *, queue, settings) -> None:  # noqa: ANN001
            pass

        async def send_kind_mail(self, recipients, **kw):  # noqa: ANN001, ANN003
            captured["recipients"] = recipients
            captured["kw"] = kw
            return True

    async def fake_actionable(session, *, state, gremium_id):  # noqa: ANN001
        return ["team@x.de"]

    async def fake_state_actionable(session, state):  # noqa: ANN001
        return True

    import app.modules.notifications.recipients as recipients_mod

    monkeypatch.setattr(mod, "NotificationService", FakeService)
    monkeypatch.setattr(
        recipients_mod, "actionable_principal_emails", fake_actionable
    )
    monkeypatch.setattr(recipients_mod, "state_actionable", fake_state_actionable)
    session = FakeSession(
        executes=[[({"title": "Beamer"}, uuid.uuid4(), None)]],
        scalar=[None],  # State-Lookup — kein Treffer nötig
    )
    disp = NotificationActionDispatcher(_sessionmaker(session), None, SETTINGS)
    await disp.dispatch([_action("taskNotify")])

    assert captured["recipients"] == ["team@x.de"]
    kw = captured["kw"]
    assert kw["kind"] == "task"  # type: ignore[index]
    assert kw["template_key"] == "task_new"  # type: ignore[index]
    assert kw["context"]["applicationTitle"] == "Beamer"  # type: ignore[index]


async def test_dispatch_task_notify_skips_non_actionable_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#9: Kein actionabler Übergang am neuen State → KEINE Task-Mail."""
    captured: dict[str, object] = {}

    class FakeService:
        def __init__(self, session, *, queue, settings) -> None:  # noqa: ANN001
            pass

        async def send_kind_mail(self, recipients, **kw):  # noqa: ANN001, ANN003
            captured["recipients"] = recipients
            return True

    async def fake_state_actionable(session, state):  # noqa: ANN001
        return False

    import app.modules.notifications.recipients as recipients_mod

    monkeypatch.setattr(mod, "NotificationService", FakeService)
    monkeypatch.setattr(recipients_mod, "state_actionable", fake_state_actionable)
    session = FakeSession(
        executes=[[({"title": "Beamer"}, uuid.uuid4(), None)]],
        scalar=[None],
    )
    disp = NotificationActionDispatcher(_sessionmaker(session), None, SETTINGS)
    await disp.dispatch([_action("taskNotify")])

    assert "recipients" not in captured  # Versand übersprungen
