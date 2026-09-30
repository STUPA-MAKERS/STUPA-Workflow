"""F6: a new flow version moves the open deadlines along (real Postgres).

Before the fix a deadline kept `action_on_pass` with a transition of the old version.
The cron could not fire it any more (`fire` refuses a transition of another flow
version), so the deadline expired without effect. The activation now re-creates the
deadline of every moved application on the new version. The reminder marker and the
consumed marker carry over when the due time stays the same. A state that keeps its
policy key keeps its due time, so a `recurring` date that passed stays passed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.schemas import FlowVersionCreate
from app.modules.admin.service import ConfigService
from app.modules.applications.models import Application
from app.modules.deadlines.models import Deadline, DeadlinePolicy
from app.modules.flow.models import State, Transition
from app.modules.flow.service import FlowService
from app.modules.forms.models import FormVersion
from tests.integration.modules.admin.test_admin_service import _make_type

pytestmark = pytest.mark.integration

_ACTOR = "oidc|admin"


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


def _graph(policy_key: str, *, label: str = "Prüfung") -> dict[str, Any]:
    return {
        "states": [
            {"key": "review", "label": {"de": label}, "isInitial": True,
             "config": {"deadlinePolicyKey": policy_key}},
            {"key": "expired", "label": {"de": "Abgelaufen"}},
        ],
        "transitions": [
            {"from": "review", "to": "expired", "label": {"de": "Frist"},
             "guard": {"deadlinePassed": True}},
        ],
    }


async def _policy(session: AsyncSession, **values: Any) -> str:
    key = f"frist-{uuid.uuid4().hex[:8]}"
    session.add(DeadlinePolicy(key=key, label={"de": "Frist"}, **values))
    await session.commit()
    return key


async def _save(session: AsyncSession, graph: dict[str, Any]) -> uuid.UUID:
    out = await ConfigService(session).create_global_flow_version(
        FlowVersionCreate.model_validate({"graph": graph}), _ACTOR
    )
    return out.id


async def _application(session: AsyncSession, version_id: uuid.UUID) -> Application:
    app_type = await _make_type(session)
    fv = FormVersion(application_type_id=app_type.id, version=1)
    session.add(fv)
    await session.flush()
    review = (
        await session.scalars(
            select(State).where(State.flow_version_id == version_id, State.key == "review")
        )
    ).one()
    app = Application(
        type_id=app_type.id, form_version_id=fv.id, flow_version_id=version_id,
        current_state_id=review.id, data={},
    )
    session.add(app)
    await session.commit()
    await session.refresh(app)
    await FlowService(session).schedule_state_deadline(app, review)
    return app


async def _deadline(session: AsyncSession, app_id: uuid.UUID) -> Deadline:
    rows = (
        await session.scalars(
            select(Deadline)
            .where(Deadline.application_id == app_id, Deadline.kind == "flow_deadline")
            .execution_options(populate_existing=True)
        )
    ).all()
    assert len(rows) == 1
    return rows[0]


async def _transition_id(session: AsyncSession, version_id: uuid.UUID) -> str:
    t = (
        await session.scalars(
            select(Transition).where(Transition.flow_version_id == version_id)
        )
    ).one()
    return str(t.id)


async def test_activation_points_the_deadline_at_the_new_version(
    session: AsyncSession,
) -> None:
    key = await _policy(session, kind="relative_submitted", offset_days=5)
    v1 = await _save(session, _graph(key))
    app = await _application(session, v1)
    before = await _deadline(session, app.id)
    assert before.action_on_pass == {"transitionId": await _transition_id(session, v1)}
    reminded = datetime.now(UTC)
    before.reminded_at = reminded
    due = before.due_at
    await session.commit()

    v2 = await _save(session, _graph(key, label="Prüfung neu"))

    after = await _deadline(session, app.id)
    assert after.action_on_pass == {"transitionId": await _transition_id(session, v2)}
    assert after.due_at == due
    # Same due time: no second reminder.
    assert after.reminded_at == reminded


async def test_activation_keeps_a_relative_changed_deadline(
    session: AsyncSession,
) -> None:
    """A flow edit is no change of the application.

    The remap must not set `updated_at` to the activation time. Otherwise every
    `relative_changed` deadline moves later and the applicant gets a second reminder.
    """
    key = await _policy(session, kind="relative_changed", offset_days=5)
    v1 = await _save(session, _graph(key))
    app = await _application(session, v1)
    changed = datetime.now(UTC) - timedelta(days=2)
    await session.execute(
        update(Application).where(Application.id == app.id).values(updated_at=changed)
    )
    await session.commit()
    await session.refresh(app)
    review = (
        await session.scalars(
            select(State).where(State.flow_version_id == v1, State.key == "review")
        )
    ).one()
    await FlowService(session).schedule_state_deadline(app, review)
    before = await _deadline(session, app.id)
    assert before.due_at == changed + timedelta(days=5)
    reminded = datetime.now(UTC)
    before.reminded_at = reminded
    await session.commit()

    v2 = await _save(session, _graph(key, label="Prüfung neu"))

    moved = (
        await session.scalars(
            select(Application)
            .where(Application.id == app.id)
            .execution_options(populate_existing=True)
        )
    ).one()
    assert moved.flow_version_id == v2
    assert moved.updated_at == changed
    after = await _deadline(session, app.id)
    assert after.due_at == changed + timedelta(days=5)
    assert after.reminded_at == reminded
    assert after.action_on_pass == {"transitionId": await _transition_id(session, v2)}


async def test_consumed_expired_deadline_stays_consumed(session: AsyncSession) -> None:
    key = await _policy(
        session, kind="absolute", absolute_at=datetime.now(UTC) - timedelta(days=1)
    )
    v1 = await _save(session, _graph(key))
    app = await _application(session, v1)
    before = await _deadline(session, app.id)
    # The cron fired it already and the guard failed: the marker is consumed.
    before.action_on_pass = None
    await session.commit()

    await _save(session, _graph(key, label="neu"))

    after = await _deadline(session, app.id)
    assert after.action_on_pass is None


async def test_changed_policy_gives_a_new_due_time(session: AsyncSession) -> None:
    short = await _policy(session, kind="relative_submitted", offset_days=5)
    long = await _policy(session, kind="relative_submitted", offset_days=30)
    v1 = await _save(session, _graph(short))
    app = await _application(session, v1)
    before = await _deadline(session, app.id)
    before.reminded_at = datetime.now(UTC)
    due = before.due_at
    await session.commit()

    v2 = await _save(session, _graph(long))

    after = await _deadline(session, app.id)
    assert after.due_at == due + timedelta(days=25)
    assert after.reminded_at is None
    assert after.action_on_pass == {"transitionId": await _transition_id(session, v2)}


async def test_state_without_policy_drops_the_deadline(session: AsyncSession) -> None:
    key = await _policy(session, kind="relative_submitted", offset_days=5)
    v1 = await _save(session, _graph(key))
    app = await _application(session, v1)
    graph = _graph(key)
    graph["states"][0]["config"] = {}
    await _save(session, graph)
    rows = (
        await session.scalars(select(Deadline).where(Deadline.application_id == app.id))
    ).all()
    assert rows == []


async def _expire(
    session: AsyncSession, app_id: uuid.UUID, *, consumed: bool
) -> tuple[datetime, datetime]:
    """Move the flow deadline of `app_id` to yesterday, as if the date passed."""
    row = await _deadline(session, app_id)
    past = datetime.now(UTC) - timedelta(days=1)
    reminded = past - timedelta(days=1)
    row.due_at = past
    row.reminded_at = reminded
    if consumed:
        row.action_on_pass = None
    await session.commit()
    return past, reminded


def _dates(*days: int) -> list[str]:
    today = datetime.now(UTC).date()
    return [(today + timedelta(days=d)).isoformat() for d in days]


async def test_recurring_expired_deadline_keeps_its_due_time(
    session: AsyncSession,
) -> None:
    """A flow edit must not roll a passed `recurring` date on to the next date.

    A second resolve gives the next date after now. `deadlinePassed` would then be
    false again, and the cron would fire the transition on the next date.
    """
    key = await _policy(
        session, kind="recurring", dates=_dates(-10, 30), timezone="Europe/Berlin"
    )
    v1 = await _save(session, _graph(key))
    app = await _application(session, v1)
    past, reminded = await _expire(session, app.id, consumed=False)

    v2 = await _save(session, _graph(key, label="Prüfung neu"))

    after = await _deadline(session, app.id)
    assert after.due_at == past
    assert after.reminded_at == reminded
    # The open deadline still fires, now on the transition of the new version.
    assert after.action_on_pass == {"transitionId": await _transition_id(session, v2)}


async def test_recurring_with_all_dates_past_keeps_the_consumed_row(
    session: AsyncSession,
) -> None:
    """With all dates past a second resolve gives no date and the row goes away."""
    key = await _policy(
        session, kind="recurring", dates=_dates(-10, 30), timezone="Europe/Berlin"
    )
    v1 = await _save(session, _graph(key))
    app = await _application(session, v1)
    past, reminded = await _expire(session, app.id, consumed=True)
    await session.execute(
        update(DeadlinePolicy)
        .where(DeadlinePolicy.key == key)
        .values(dates=_dates(-10, -1))
    )
    await session.commit()

    await _save(session, _graph(key, label="Prüfung neu"))

    after = await _deadline(session, app.id)
    assert after.due_at == past
    assert after.reminded_at == reminded
    assert after.action_on_pass is None
