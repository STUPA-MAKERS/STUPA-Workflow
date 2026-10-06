"""A1: a manual transition picks the meeting for its agenda item (real Postgres).

`GET /applications/{id}/transitions` flags the transitions with `addToNextSession`
into a vote state (`addsToAgenda`, `agendaGremiumId`). `fire(..., meeting_id=...)`
checks the meeting before the state change and adds the agenda item in the same
transaction. A refused meeting gives 422, a failed guard gives 409, and in both cases
nothing changes: no state change, no status event, no agenda item.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.models import Application, StatusEvent
from app.modules.auth.principal import Principal
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.models import State, Transition
from app.modules.flow.service import FlowService
from app.modules.livevote.models import MeetingAgendaItem
from app.shared.errors import ConflictError, ValidationProblem
from tests.integration.modules.flow.agenda_support import (
    admin,
    make_application,
    make_meeting,
    seed_agenda_flow,
)

pytestmark = pytest.mark.integration


class _Recorder:
    def __init__(self) -> None:
        self.actions: list[DispatchedAction] = []

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        self.actions.extend(actions)


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _unchanged(session: AsyncSession, app_id: uuid.UUID, review_id: uuid.UUID) -> None:
    """Assert that the refused fire left no trace.

    The ids come in as plain values: a rollback expires the ORM objects.
    """
    state_id = await session.scalar(
        select(Application.current_state_id).where(Application.id == app_id)
    )
    assert state_id == review_id
    items = await session.scalar(
        select(func.count()).select_from(MeetingAgendaItem).where(
            MeetingAgendaItem.application_id == app_id
        )
    )
    assert items == 0
    events = await session.scalar(
        select(func.count()).select_from(StatusEvent).where(
            StatusEvent.application_id == app_id,
            StatusEvent.transition_id.is_not(None),
        )
    )
    assert events == 0


async def test_transitions_flag_the_agenda_action(session: AsyncSession) -> None:
    flow = await seed_agenda_flow(session)
    app = await make_application(session, flow)
    out = {t.id: t for t in await FlowService(session).available_transitions(app.id, admin())}
    assert out[flow.to_vote.id].adds_to_agenda is True
    assert out[flow.to_vote.id].agenda_gremium_id == flow.gremium.id
    assert out[flow.plain.id].adds_to_agenda is False
    assert out[flow.plain.id].agenda_gremium_id is None
    # The action into a normal state takes no meeting: the UI fires it without one.
    assert out[flow.to_done.id].adds_to_agenda is False
    assert out[flow.to_done.id].agenda_gremium_id is None
    body = out[flow.to_vote.id].model_dump(by_alias=True)
    assert body["addsToAgenda"] is True
    assert body["agendaGremiumId"] == flow.gremium.id


async def test_fire_with_meeting_adds_the_item_atomically(session: AsyncSession) -> None:
    flow = await seed_agenda_flow(session)
    app = await make_application(session, flow)
    today = date.today()
    nxt = await make_meeting(session, flow.gremium, day=today + timedelta(days=1))
    chosen = await make_meeting(session, flow.gremium, day=today + timedelta(days=14))
    rec = _Recorder()

    result = await FlowService(session, rec).fire(
        app.id, flow.to_vote.id, admin(), note="TOP", meeting_id=chosen.id,
        non_public=True,
    )

    assert result.new_state_id == flow.states["voting"].id
    # The post-commit action does not run a second time.
    assert "addToNextSession" not in result.dispatched_actions
    assert all(a.type != "addToNextSession" for a in rec.actions)
    items = (
        await session.scalars(
            select(MeetingAgendaItem).where(MeetingAgendaItem.application_id == app.id)
        )
    ).all()
    assert [(i.meeting_id, i.non_public) for i in items] == [(chosen.id, True)]
    assert nxt.id != chosen.id


async def test_fire_without_meeting_keeps_the_post_commit_action(
    session: AsyncSession,
) -> None:
    flow = await seed_agenda_flow(session)
    app = await make_application(session, flow)
    rec = _Recorder()
    result = await FlowService(session, rec).fire(app.id, flow.to_vote.id, admin())
    assert "addToNextSession" in result.dispatched_actions
    assert any(a.type == "addToNextSession" for a in rec.actions)


@pytest.mark.parametrize(
    "case",
    ["live", "closed", "other_gremium", "unknown", "no_action", "normal_target", "hidden"],
)
async def test_fire_with_unfit_meeting_is_422(session: AsyncSession, case: str) -> None:
    flow = await seed_agenda_flow(session)
    app = await make_application(session, flow)
    app_id, review_id = app.id, flow.states["review"].id
    day = date.today() + timedelta(days=1)
    transition = flow.to_vote
    principal: Principal = admin()
    if case in ("live", "closed"):
        meeting_id = (await make_meeting(session, flow.gremium, day=day, status=case)).id
    elif case == "other_gremium":
        meeting_id = (await make_meeting(session, flow.other_gremium, day=day)).id
    elif case == "unknown":
        meeting_id = uuid.uuid4()
    else:
        meeting_id = (await make_meeting(session, flow.gremium, day=day)).id
        if case == "no_action":
            transition = flow.plain
        elif case == "normal_target":
            transition = flow.to_done
        else:
            # Not an admin, no membership: the meeting is not visible.
            principal = Principal(sub="stranger", permissions={"application.transition"})

    with pytest.raises(ValidationProblem) as exc:
        await FlowService(session).fire(
            app.id, transition.id, principal, meeting_id=meeting_id
        )
    assert exc.value.status == 422
    assert exc.value.code == "agenda_meeting_invalid"
    await _unchanged(session, app_id, review_id)


async def test_guard_failure_leaves_no_item(session: AsyncSession) -> None:
    flow = await seed_agenda_flow(session)
    app = await make_application(session, flow)
    app_id, review_id = app.id, flow.states["review"].id
    meeting = await make_meeting(session, flow.gremium, day=date.today())
    row = await session.get(Transition, flow.to_vote.id)
    assert row is not None
    row.guard = {"roleIs": "nobody"}
    await session.commit()

    with pytest.raises(ConflictError):
        await FlowService(session).fire(
            app.id, flow.to_vote.id, admin(), meeting_id=meeting.id
        )
    await _unchanged(session, app_id, review_id)


async def test_refused_agenda_insert_rolls_back_the_state_change(
    session: AsyncSession,
) -> None:
    """The meeting fits the action, but the vote state belongs to another Gremium.

    The agenda insert then refuses the application after the state change. The engine
    rolls the whole transaction back and answers 422.
    """
    flow = await seed_agenda_flow(session)
    app = await make_application(session, flow)
    app_id, review_id = app.id, flow.states["review"].id
    to_vote_id = flow.to_vote.id
    meeting = await make_meeting(session, flow.gremium, day=date.today())
    voting = await session.get(State, flow.states["voting"].id)
    assert voting is not None
    voting.config = {"gremiumId": str(flow.other_gremium.id)}
    await session.commit()

    with pytest.raises(ValidationProblem):
        await FlowService(session).fire(app_id, to_vote_id, admin(), meeting_id=meeting.id)
    await _unchanged(session, app_id, review_id)
