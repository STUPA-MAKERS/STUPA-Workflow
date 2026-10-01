"""F15, F18, O14: an unconfirmed guest application rests in the flow (real Postgres).

A guest submission starts with `email_confirmed_at IS NULL`. Until the magic-link
verify confirms it:

* the flow routes answer 404 (F15),
* the create schedules no deadline, the cron fires no deadline action, sends no
  reminder and fires no automatic transition (F18),
* the notify dispatcher sends no flow mail (O14).

The first verify starts the flow one time: it schedules the deadline of the current
state, runs `auto_advance` and sends the task mail of the state. A second verify
starts nothing.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.main as main_mod
from app.db import get_session
from app.deps import get_current_principal
from app.main import create_app
from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application, StatusEvent
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth import service as auth_service
from app.modules.auth.principal import Principal
from app.modules.deadlines.models import Deadline, DeadlinePolicy
from app.modules.deadlines.service import DeadlineService
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.notifications.action_dispatcher import NotificationActionDispatcher
from app.modules.notifications.mail import MailMessage
from app.settings import Settings, get_settings, load_settings
from app.shared.config_schemas import FormFieldDef
from worker.deadlines import process_deadlines

pytestmark = pytest.mark.integration


class _Recorder:
    """Flow dispatcher fake that records the actions and keeps Redis out."""

    def __init__(self) -> None:
        self.actions: list[DispatchedAction] = []

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        self.actions.extend(actions)


class _ListQueue:
    """Mail queue fake that keeps the enqueued messages."""

    def __init__(self) -> None:
        self.messages: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.messages.append(msg)


class _Seed:
    def __init__(self, type_id: uuid.UUID, states: dict[str, State],
                 transition_id: uuid.UUID) -> None:
        self.type_id = type_id
        self.states = states
        self.transition_id = transition_id


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return load_settings(
        database_url=migrated[1],
        session_secret="session-secret-unconfirmed-rest",
        magic_link_secret="magic-link-secret-unconfirmed0",
        cookie_secure=False,
    )


async def _seed(
    maker: async_sessionmaker[AsyncSession], *, automatic: bool
) -> _Seed:
    """Create a type, a deadline policy and a flow `eingang` -> `pruefung`.

    The initial state `eingang` carries a `relative_submitted` policy of 3 days. The
    one transition is automatic when `automatic` is true, else manual.
    """
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        gremium = Gremium(name="G", slug=f"g-{tag}")
        session.add(gremium)
        await session.flush()
        app_type = ApplicationType(
            gremium_id=gremium.id, key=f"t-{tag}", name_i18n={}, has_budget=False
        )
        policy = DeadlinePolicy(
            key=f"frist-{tag}", label={"de": "Frist"}, kind="relative_submitted",
            offset_days=3,
        )
        session.add_all([app_type, policy])
        await session.commit()
        await FormsService(session).create_form_version(
            app_type.id,
            FormVersionCreate(
                fields=[FormFieldDef(key="title", type="text", label={"de": "Titel"},
                                     required=True)],
                activate=True,
            ),
            "tester",
        )
        flow = FlowVersion(version=1, active=True, editor_layout={})
        session.add(flow)
        await session.flush()
        states = {
            "eingang": State(flow_version_id=flow.id, key="eingang",
                             label_i18n={"de": "Eingang"}, edit_allowed=True,
                             is_initial=True, config={"deadlinePolicyKey": policy.key}),
            "pruefung": State(flow_version_id=flow.id, key="pruefung",
                              label_i18n={"de": "Prüfung"}, edit_allowed=False),
        }
        session.add_all(list(states.values()))
        await session.flush()
        transition = Transition(
            flow_version_id=flow.id, from_state_id=states["eingang"].id,
            to_state_id=states["pruefung"].id, label_i18n={"de": "Prüfen"},
            guard=None, actions=[], order=0, automatic=automatic,
        )
        session.add(transition)
        await session.commit()
        return _Seed(app_type.id, states, transition.id)


def _payload(type_id: uuid.UUID) -> ApplicationCreate:
    return ApplicationCreate.model_validate(
        {"typeId": str(type_id), "data": {"title": "Gastantrag"},
         "applicantEmail": "gast@example.org", "lang": "de"}
    )


async def _guest_create(
    maker: async_sessionmaker[AsyncSession], seed: _Seed, recorder: _Recorder
) -> uuid.UUID:
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            _payload(seed.type_id), dispatcher=recorder
        )
        assert app.email_confirmed_at is None
        return app.id


async def _magic_token(
    maker: async_sessionmaker[AsyncSession], settings: Settings, app_id: uuid.UUID
) -> str:
    """Issue a magic link for the application and return its token."""
    links: list[str] = []

    def _deliver(_email: str, link: str) -> None:
        links.append(link)

    async with maker() as session:
        await auth_service.request_magic_link(
            session, settings, email="gast@example.org", application_id=app_id,
            deliver=_deliver,
        )
        await session.commit()
    (link,) = links
    match = re.search(r"#t=(.+)$", link)
    assert match is not None
    return match.group(1)


async def _verify(
    maker: async_sessionmaker[AsyncSession], settings: Settings, token: str,
    recorder: _Recorder,
) -> None:
    async with maker() as session:
        await auth_service.verify_magic_link(
            session, settings, token=token, dispatcher=recorder
        )
        await session.commit()


async def _deadlines(
    maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID
) -> list[Deadline]:
    async with maker() as session:
        return list(
            (
                await session.scalars(
                    select(Deadline).where(Deadline.application_id == app_id)
                )
            ).all()
        )


async def _app(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID) -> Application:
    async with maker() as session:
        app = await session.get(Application, app_id)
        assert app is not None
        return app


# F15: the flow routes hide an unconfirmed application.
@pytest.fixture
def api(
    migrated: tuple[str, str], settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FastAPI]:
    # The TestClient runs the app on its own event loop. It gets its own engine
    # without a pool, so no connection crosses the loops.
    maker = async_sessionmaker(
        create_async_engine(migrated[1], poolclass=NullPool), expire_on_commit=False
    )

    async def _request_session() -> AsyncIterator[AsyncSession]:
        async with maker() as db:
            yield db

    monkeypatch.setattr(main_mod, "get_sessionmaker", lambda: maker)
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_session] = _request_session
    application.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin-flow", roles=["admin"]
    )
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


async def test_flow_routes_answer_404_until_the_verify(
    maker: async_sessionmaker[AsyncSession], settings: Settings, api: FastAPI
) -> None:
    seed = await _seed(maker, automatic=False)
    app_id = await _guest_create(maker, seed, _Recorder())
    base = f"/api/applications/{app_id}"

    with TestClient(api) as client:
        assert client.get(f"{base}/transitions").status_code == 404
        assert client.get(f"{base}/flow-states").status_code == 404
        fire = client.post(
            f"{base}/transition", json={"transitionId": str(seed.transition_id)}
        )
        assert fire.status_code == 404, fire.text
        force = client.post(
            f"{base}/force-status",
            json={"stateId": str(seed.states["pruefung"].id), "note": "x"},
        )
        assert force.status_code == 404, force.text

    # Nothing moved.
    assert (await _app(maker, app_id)).current_state_id == seed.states["eingang"].id

    await _verify(maker, settings, await _magic_token(maker, settings, app_id), _Recorder())

    with TestClient(api) as client:
        listed = client.get(f"{base}/transitions")
        assert listed.status_code == 200, listed.text
        assert [t["id"] for t in listed.json()] == [str(seed.transition_id)]
        assert client.get(f"{base}/flow-states").status_code == 200


# F18 and O14: no deadline, no automatic transition and no mail before the verify.
async def test_unconfirmed_application_rests_in_the_cron(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await _seed(maker, automatic=True)
    recorder = _Recorder()
    app_id = await _guest_create(maker, seed, recorder)

    # The create schedules no deadline and starts nothing.
    assert await _deadlines(maker, app_id) == []
    assert recorder.actions == []

    # A deadline row from before this fix is due and has an action. The scans skip it.
    past = datetime.now(UTC) - timedelta(hours=1)
    async with maker() as session:
        legacy = await DeadlineService(session).create(
            kind="flow_deadline", due_at=past, application_id=app_id,
            action_on_pass={"transitionId": str(seed.transition_id)},
        )
    async with maker() as session:
        svc = DeadlineService(session)
        now = datetime.now(UTC)
        assert legacy.id not in await svc.due_action_deadline_ids(now)
        assert legacy.id not in await svc.due_reminder_ids(now, timedelta(days=1))

    ctx: dict[str, Any] = {
        "settings": settings,
        "deadlines_sessionmaker": maker,
        "flow_dispatcher": recorder,
        "mail_queue": _ListQueue(),
    }
    await process_deadlines(ctx)

    app = await _app(maker, app_id)
    assert app.current_state_id == seed.states["eingang"].id
    assert recorder.actions == []
    assert ctx["mail_queue"].messages == []
    (row,) = await _deadlines(maker, app_id)
    assert row.reminded_at is None
    assert row.action_on_pass is not None  # not consumed


async def test_notify_dispatcher_holds_back_flow_mails(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await _seed(maker, automatic=False)
    app_id = await _guest_create(maker, seed, _Recorder())
    queue = _ListQueue()
    dispatcher = NotificationActionDispatcher(
        sessionmaker=maker, queue=queue, settings=settings
    )
    async with maker() as session:
        event_id = await session.scalar(
            select(StatusEvent.id).where(StatusEvent.application_id == app_id)
        )
    assert event_id is not None
    action = DispatchedAction(
        type="notify", application_id=app_id, transition_id=seed.transition_id,
        status_event_id=event_id, idempotency_key=f"{app_id}:{event_id}:0:notify",
        params={"templateKey": "status_update", "recipients": [{"kind": "applicant"}]},
    )

    await dispatcher.dispatch([action])
    assert queue.messages == []

    # The same action goes out once the email is confirmed.
    async with maker() as session:
        app = await session.get(Application, app_id)
        assert app is not None
        app.email_confirmed_at = datetime.now(UTC)
        await session.commit()
    await dispatcher.dispatch([action])
    assert [m.to for m in queue.messages] == [("gast@example.org",)]


# Item 3 of the plan: the verify starts the flow, one time.
async def test_verify_schedules_the_deadline_and_announces_once(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await _seed(maker, automatic=False)
    app_id = await _guest_create(maker, seed, _Recorder())
    token = await _magic_token(maker, settings, app_id)

    recorder = _Recorder()
    await _verify(maker, settings, token, recorder)

    app = await _app(maker, app_id)
    assert app.email_confirmed_at is not None
    assert app.current_state_id == seed.states["eingang"].id
    (deadline,) = await _deadlines(maker, app_id)
    assert deadline.kind == "flow_deadline"
    assert deadline.due_at == app.created_at + timedelta(days=3)
    (action,) = recorder.actions
    assert action.type == "taskNotify"
    assert action.transition_id is None

    # The edit link is not single-use. A second click starts nothing again.
    second = _Recorder()
    await _verify(maker, settings, token, second)
    assert second.actions == []
    (again,) = await _deadlines(maker, app_id)
    assert again.id == deadline.id


async def test_verify_runs_the_automatic_transition(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await _seed(maker, automatic=True)
    app_id = await _guest_create(maker, seed, _Recorder())

    recorder = _Recorder()
    await _verify(maker, settings, await _magic_token(maker, settings, app_id), recorder)

    app = await _app(maker, app_id)
    assert app.current_state_id == seed.states["pruefung"].id
    async with maker() as session:
        events = (
            await session.scalars(
                select(StatusEvent)
                .where(StatusEvent.application_id == app_id)
                .order_by(StatusEvent.at)
            )
        ).all()
    assert [e.actor for e in events] == ["applicant", "system:confirmation"]
    # The fired transition sends its own mails. No extra task mail of `eingang`.
    assert {a.type for a in recorder.actions} == {"notify", "taskNotify"}
    assert all(a.status_event_id == events[-1].id for a in recorder.actions)
    # `pruefung` has no deadline policy, so the start leaves no deadline behind.
    assert await _deadlines(maker, app_id) == []


async def test_logged_in_create_starts_the_flow_at_once(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    seed = await _seed(maker, automatic=False)
    recorder = _Recorder()
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            _payload(seed.type_id), actor="member-1", dispatcher=recorder
        )
    assert app.email_confirmed_at is not None
    (deadline,) = await _deadlines(maker, app.id)
    assert deadline.kind == "flow_deadline"
    assert [a.type for a in recorder.actions] == ["taskNotify"]
