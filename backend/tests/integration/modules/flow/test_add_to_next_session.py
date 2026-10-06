"""F3: `addToNextSession` picks the next PLANNED meeting (real Postgres).

Before the fix the query filtered on the status `finalized`, which does not exist. A
live or closed meeting of today could therefore get the agenda item. The action now
takes the earliest meeting of the Gremium with `status = planned` and a date of today
or later in local time. Without such a meeting it only logs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.flow.extras_dispatcher import FlowExtrasActionDispatcher
from app.modules.flow.service import FlowService
from app.modules.livevote.models import MeetingAgendaItem
from app.settings import get_settings
from tests.integration.modules.flow.agenda_support import (
    admin,
    make_application,
    make_meeting,
    seed_agenda_flow,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


def _today() -> datetime:
    return datetime.now(ZoneInfo(get_settings().local_timezone))


async def _items(session: AsyncSession, application_id: object) -> list[MeetingAgendaItem]:
    return list(
        (
            await session.scalars(
                select(MeetingAgendaItem).where(
                    MeetingAgendaItem.application_id == application_id
                )
            )
        ).all()
    )


async def test_next_planned_meeting_gets_the_item(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    today = _today().date()
    async with maker() as session:
        flow = await seed_agenda_flow(session)
        app = await make_application(session, flow)
        # A live and a closed meeting of today, a planned one of yesterday and one of
        # another Gremium: none of them may get the item.
        await make_meeting(session, flow.gremium, day=today, status="live")
        await make_meeting(session, flow.gremium, day=today, status="closed")
        await make_meeting(session, flow.gremium, day=today - timedelta(days=1))
        await make_meeting(session, flow.other_gremium, day=today)
        later = await make_meeting(session, flow.gremium, day=today + timedelta(days=7))
        nxt = await make_meeting(session, flow.gremium, day=today + timedelta(days=1))

        extras = FlowExtrasActionDispatcher(maker)
        await FlowService(session, extras).fire(app.id, flow.to_vote.id, admin())

        items = await _items(session, app.id)
    assert [i.meeting_id for i in items] == [nxt.id]
    assert later.id != nxt.id


async def test_planned_meeting_of_today_counts(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    today = _today().date()
    async with maker() as session:
        flow = await seed_agenda_flow(session)
        app = await make_application(session, flow)
        await make_meeting(session, flow.gremium, day=today + timedelta(days=3))
        todays = await make_meeting(session, flow.gremium, day=today)

        await FlowService(session, FlowExtrasActionDispatcher(maker)).fire(
            app.id, flow.to_vote.id, admin()
        )
        items = await _items(session, app.id)
    assert [i.meeting_id for i in items] == [todays.id]


async def test_no_planned_meeting_skips_the_item(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    today = _today().date()
    async with maker() as session:
        flow = await seed_agenda_flow(session)
        app = await make_application(session, flow)
        await make_meeting(session, flow.gremium, day=today, status="live")
        await make_meeting(session, flow.gremium, day=today + timedelta(days=2),
                           status="closed")

        result = await FlowService(session, FlowExtrasActionDispatcher(maker)).fire(
            app.id, flow.to_vote.id, admin()
        )
        items = await _items(session, app.id)
    # The state change stays; the action only logs.
    assert result.new_state_id == flow.states["voting"].id
    assert items == []
