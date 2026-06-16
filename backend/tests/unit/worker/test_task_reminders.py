"""Tests der Aufgaben-Erinnerungen (#task-reminder) — Worker + Admin-API ohne DB."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

import worker.task_reminders as mod
from app.deps import get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.flow.models import State
from app.modules.notifications.models import NotificationSettings, TaskReminderLog
from app.modules.notifications.router import get_notification_service
from app.settings import load_settings
from tests._support.notifications_fakes import FakeQueue, FakeSession
from worker.task_reminders import process_task_reminders

SETTINGS = load_settings()
NOW = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)


def _config(
    *, enabled: bool = True, after_days: int = 5, repeat_days: int = 7
) -> NotificationSettings:
    return NotificationSettings(
        id=1,
        task_reminder_enabled=enabled,
        task_reminder_after_days=after_days,
        task_reminder_repeat_days=repeat_days,
    )


def _state(kind: str = "normal") -> State:
    return State(
        id=uuid.uuid4(),
        flow_version_id=uuid.uuid4(),
        key="review",
        label_i18n={"de": "Prüfung"},
        kind=kind,
        config={},
    )


def _ctx(session: FakeSession, queue: FakeQueue) -> dict[str, Any]:
    class _CM:
        async def __aenter__(self) -> FakeSession:
            return session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return {"sessionmaker": lambda: _CM(), "mail_queue": queue, "settings": SETTINGS}


@pytest.fixture(autouse=True)
def _patch_recipients(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_actionable(session: Any, *, state: Any, gremium_id: Any) -> list[str]:
        return ["team@x.de"]

    monkeypatch.setattr(mod, "actionable_principal_emails", fake_actionable)


async def test_disabled_sends_nothing() -> None:
    session = FakeSession()
    session.add(_config(enabled=False))
    queue = FakeQueue()
    assert await process_task_reminders(_ctx(session, queue), now=NOW) == 0
    assert queue.messages == []


async def test_stale_application_gets_reminder() -> None:
    app_id, event_id = uuid.uuid4(), uuid.uuid4()
    state = _state()
    entered = NOW - timedelta(days=6)
    session = FakeSession(
        executes=[
            [(app_id, state.id, entered)],  # due-Kandidaten
            [({"title": "Beamer"}, None)],  # _remind_one: Antrag
        ],
        scalars=[
            [state],  # States
            [],  # bestehende Logs
            [],  # Präferenz-Filter (#4-2, keine Abwahlen)
            [],  # Template-Lookup (kein DB-Override)
        ],
        scalar=[
            1,  # _state_actionable: manuelle Übergänge
            event_id,  # letztes status_event
        ],
    )
    session.add(_config(after_days=5))
    queue = FakeQueue()

    sent = await process_task_reminders(_ctx(session, queue), now=NOW)

    assert sent == 1
    assert len(queue.messages) == 1
    msg = queue.messages[0]
    assert msg.to == ("team@x.de",)
    assert "Beamer" in msg.subject
    assert "6 Tagen" in msg.text
    log = next(a for a in session.added if isinstance(a, TaskReminderLog))
    assert log.application_id == app_id
    assert log.status_event_id == event_id
    assert log.reminded_at == NOW


async def test_once_mode_skips_already_reminded_stay() -> None:
    app_id, event_id = uuid.uuid4(), uuid.uuid4()
    state = _state()
    log = TaskReminderLog(
        application_id=app_id,
        status_event_id=event_id,
        reminded_at=NOW - timedelta(days=30),
    )
    session = FakeSession(
        executes=[[(app_id, state.id, NOW - timedelta(days=40))]],
        scalars=[[state], [log]],
        scalar=[1, event_id],
    )
    session.add(_config(repeat_days=0))  # Einmal-Modus
    queue = FakeQueue()
    assert await process_task_reminders(_ctx(session, queue), now=NOW) == 0
    assert queue.messages == []


async def test_repeat_mode_reminds_again_after_interval() -> None:
    app_id, event_id = uuid.uuid4(), uuid.uuid4()
    state = _state()
    log = TaskReminderLog(
        application_id=app_id,
        status_event_id=event_id,
        reminded_at=NOW - timedelta(days=8),
    )
    session = FakeSession(
        executes=[
            [(app_id, state.id, NOW - timedelta(days=20))],
            [({"title": "Beamer"}, None)],
        ],
        scalars=[[state], [log], [], []],
        scalar=[1, event_id],
    )
    session.store[app_id] = log  # session.get(TaskReminderLog, app_id)
    session.add(_config(repeat_days=7))
    queue = FakeQueue()

    assert await process_task_reminders(_ctx(session, queue), now=NOW) == 1
    assert log.reminded_at == NOW  # Log fortgeschrieben, keine zweite Zeile


async def test_vote_state_counts_as_actionable() -> None:
    app_id, event_id = uuid.uuid4(), uuid.uuid4()
    state = _state(kind="vote")
    session = FakeSession(
        executes=[
            [(app_id, state.id, NOW - timedelta(days=6))],
            [({}, None)],
        ],
        # vote-State → kein Transition-Count-scalar nötig
        scalars=[[state], [], [], []],
        scalar=[event_id],
    )
    session.add(_config())
    queue = FakeQueue()
    assert await process_task_reminders(_ctx(session, queue), now=NOW) == 1


# --------------------------------------------------------------- Admin-API (#6)
class _FakeService:
    def __init__(self) -> None:
        self.updated: dict[str, Any] | None = None
        self.row = _config()

    async def get_notification_settings(self) -> NotificationSettings:
        return self.row

    async def update_notification_settings(self, **kw: Any) -> NotificationSettings:
        self.updated = kw
        if kw.get("task_reminder_after_days") is not None:
            self.row.task_reminder_after_days = kw["task_reminder_after_days"]
        return self.row


def _client(service: _FakeService, principal: Principal | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_notification_service] = lambda: service
    app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app)


def test_settings_require_admin_notifications() -> None:
    client = _client(_FakeService(), Principal(sub="u", permissions={"admin.site"}))
    assert client.get("/api/admin/notification-settings").status_code == 403


def test_settings_roundtrip() -> None:
    service = _FakeService()
    client = _client(
        service, Principal(sub="u", permissions={"admin.notifications"})
    )
    r = client.get("/api/admin/notification-settings")
    assert r.status_code == 200
    assert r.json() == {
        "taskReminderEnabled": True,
        "taskReminderAfterDays": 5,
        "taskReminderRepeatDays": 7,
    }
    r = client.put(
        "/api/admin/notification-settings", json={"taskReminderAfterDays": 3}
    )
    assert r.status_code == 200
    assert r.json()["taskReminderAfterDays"] == 3
    assert service.updated == {
        "actor": "u",
        "task_reminder_enabled": None,
        "task_reminder_after_days": 3,
        "task_reminder_repeat_days": None,
    }


def test_settings_reject_invalid_values() -> None:
    client = _client(
        _FakeService(), Principal(sub="u", permissions={"admin.notifications"})
    )
    assert (
        client.put(
            "/api/admin/notification-settings", json={"taskReminderAfterDays": 0}
        ).status_code
        == 422
    )
