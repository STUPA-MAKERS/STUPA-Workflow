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
from tests.notifications_fakes import FakeSession

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
    session = FakeSession(scalar=[app_type_id])
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
    session = FakeSession(scalar=[None])
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
