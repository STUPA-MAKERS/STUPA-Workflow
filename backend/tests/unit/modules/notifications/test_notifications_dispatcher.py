"""Tests of the `notify` flow action dispatcher (T-18) with a fake service."""

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
    assert called == []  # the dispatcher never built or called the service


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
    """`taskNotify` (#4-3) resolves the recipients at send time and uses send_kind_mail."""
    captured: dict[str, object] = {}

    class FakeService:
        def __init__(self, session, *, queue, settings) -> None:  # noqa: ANN001
            pass

        async def send_kind_mail(self, recipients, **kw):  # noqa: ANN001, ANN003
            captured["recipients"] = recipients
            captured["kw"] = kw
            return True

    async def fake_actionable(session, *, application_id, state):  # noqa: ANN001
        captured["application_id"] = application_id
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
        executes=[[({"title": "Beamer"}, uuid.uuid4())]],
        scalar=[None],  # the state lookup needs no hit
    )
    disp = NotificationActionDispatcher(_sessionmaker(session), None, SETTINGS)
    action = _action("taskNotify")
    await disp.dispatch([action])

    assert captured["recipients"] == ["team@x.de"]
    assert captured["application_id"] == action.application_id
    kw = captured["kw"]
    assert kw["kind"] == "task"  # type: ignore[index]
    assert kw["template_key"] == "task_new"  # type: ignore[index]
    assert kw["context"]["applicationTitle"] == "Beamer"  # type: ignore[index]


async def test_dispatch_task_notify_skips_non_actionable_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#9: the new state has no actionable transition, so no task mail goes out."""
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
        executes=[[({"title": "Beamer"}, uuid.uuid4())]],
        scalar=[None],
    )
    disp = NotificationActionDispatcher(_sessionmaker(session), None, SETTINGS)
    await disp.dispatch([_action("taskNotify")])

    assert "recipients" not in captured  # the dispatcher skipped the send


# --- #19: the applicant mail follows the language of the application ---------


class _CapturingService:
    """Record the keyword arguments that the dispatcher gives to the service."""

    captured: dict[str, object] = {}

    def __init__(self, session, *, queue, settings) -> None:  # noqa: ANN001
        pass

    async def handle_notify_action(self, action, **kw):  # noqa: ANN001, ANN003
        type(self).captured.update(kw)
        return 1


def _capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Install the capturing service and return the dict that it fills."""
    _CapturingService.captured.clear()
    monkeypatch.setattr(mod, "NotificationService", _CapturingService)
    return _CapturingService.captured


def _applicant_notify(params: dict) -> DispatchedAction:
    return _action("notify", params)


async def test_applicant_only_notify_uses_the_application_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#19: an English application gets an English mail, with the status label.

    The test drives the real `NotificationService`, so the assertion covers the
    rendered subject and body, not only the language argument.
    """
    from app.modules.notifications.service import NotificationService
    from tests._support.notifications_fakes import FakeQueue, FakeResolver

    class _Service(NotificationService):
        def __init__(self, session, *, queue, settings) -> None:  # noqa: ANN001
            super().__init__(session, queue=queue, settings=settings)
            self.resolver = FakeResolver(["applicant@example.org"])  # type: ignore[assignment]

    monkeypatch.setattr(mod, "NotificationService", _Service)
    state_id = uuid.uuid4()
    session = FakeSession(
        executes=[
            [(uuid.uuid4(), state_id, {"title": "Beamer"})],  # the application row
            [("en", None)],  # resolve_application_lang: application.lang is en
        ],
        scalar=[{"de": "Genehmigt", "en": "Approved"}],  # the state label
        scalars=[[], []],  # nobody opted out, and no template override in the DB
    )
    queue = FakeQueue()
    disp = NotificationActionDispatcher(_sessionmaker(session), queue, SETTINGS)
    await disp.dispatch(
        [
            _applicant_notify(
                {
                    "templateKey": "status_update",
                    "recipients": [{"kind": "applicant"}],
                }
            )
        ]
    )

    assert len(queue.messages) == 1
    msg = queue.messages[0]
    assert msg.subject == "Update on your application"
    assert "New status: Approved" in msg.text
    assert "Genehmigt" not in msg.text


async def test_applicant_only_notify_without_a_state_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A state without a label leaves `status` out, and the language still resolves."""
    captured = _capture(monkeypatch)
    session = FakeSession(
        executes=[
            [(uuid.uuid4(), uuid.uuid4(), None)],  # the application row, with a state
            [("en", None)],  # resolve_application_lang
        ],
        scalar=[None],  # the state carries no label
    )
    disp = NotificationActionDispatcher(_sessionmaker(session), None, SETTINGS)
    await disp.dispatch([_applicant_notify({"recipients": [{"kind": "applicant"}]})])
    assert captured["lang"] == "en"
    assert "status" not in captured["context"]  # type: ignore[operator]


async def test_explicit_lang_param_wins_over_the_application_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `lang` param on the action stays as it is, so no resolve runs."""
    captured = _capture(monkeypatch)
    session = FakeSession(executes=[[(uuid.uuid4(), None, None)]])
    disp = NotificationActionDispatcher(_sessionmaker(session), None, SETTINGS)
    await disp.dispatch(
        [_applicant_notify({"lang": "de", "recipients": [{"kind": "applicant"}]})]
    )
    assert captured["lang"] == "de"


async def test_mixed_recipients_keep_the_default_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Applicant and team in one action share one message, so the default stays."""
    captured = _capture(monkeypatch)
    session = FakeSession(executes=[[(uuid.uuid4(), None, None)]])
    disp = NotificationActionDispatcher(_sessionmaker(session), None, SETTINGS)
    await disp.dispatch(
        [
            _applicant_notify(
                {
                    "recipients": [
                        {"kind": "applicant"},
                        {"kind": "gremium", "value": "stupa"},
                    ]
                }
            )
        ]
    )
    assert captured["lang"] is None


async def test_team_only_recipients_keep_the_default_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mail without an applicant recipient keeps the configured default language."""
    captured = _capture(monkeypatch)
    session = FakeSession(executes=[[(uuid.uuid4(), None, None)]])
    disp = NotificationActionDispatcher(_sessionmaker(session), None, SETTINGS)
    await disp.dispatch(
        [_applicant_notify({"recipients": [{"kind": "gremium", "value": "stupa"}]})]
    )
    assert captured["lang"] is None


async def test_notify_without_recipients_keeps_the_default_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An action without a recipient list resolves no language."""
    captured = _capture(monkeypatch)
    session = FakeSession(executes=[[(uuid.uuid4(), None, None)]])
    disp = NotificationActionDispatcher(_sessionmaker(session), None, SETTINGS)
    await disp.dispatch([_applicant_notify({"templateKey": "status_update"})])
    assert captured["lang"] is None


async def test_notify_with_non_dict_recipients_keeps_the_default_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The service drops the non-dict JSONB entries, so no applicant stays."""
    captured = _capture(monkeypatch)
    session = FakeSession(executes=[[(uuid.uuid4(), None, None)]])
    disp = NotificationActionDispatcher(_sessionmaker(session), None, SETTINGS)
    await disp.dispatch([_applicant_notify({"recipients": ["applicant"]})])
    assert captured["lang"] is None
