"""O12 and O25 under concurrency: the meeting row serializes close, open and remove.

The meeting close, the vote open and the agenda-item remove all lock the meeting row
first. The tests hold that lock in one session and start the other operation in a
second session. The second operation must wait, and after the commit of the first it
must see the new state:

* A vote open that waits on a close refuses the closed meeting (409 ``meeting_closed``).
* A close that waits on a vote open sees the open vote (409 ``open_vote``).
* A remove that waits on a vote open sees the open vote (409 ``agenda_item_has_vote``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.livevote.agenda_service import AgendaService
from app.modules.livevote.models import Meeting
from app.modules.livevote.schemas import MeetingPatch
from app.modules.livevote.service import MeetingService
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteCreateInternal
from app.modules.voting.service import VotingService
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, NotFoundError
from tests.integration.modules.livevote.conftest import ADMIN_SUB, admin, seed

pytestmark = pytest.mark.integration

# Long enough for the second session to reach the row lock and block on it.
_SETTLE = 0.5


async def _blocked(task: asyncio.Task[Any]) -> None:
    """Assert that the task waits on the row lock."""
    await asyncio.sleep(_SETTLE)
    assert not task.done(), "the operation did not wait for the meeting row lock"


def _spawn(coro: Awaitable[Any]) -> asyncio.Task[Any]:
    async def _run() -> Any:
        return await coro

    return asyncio.create_task(_run())


async def test_open_waits_for_a_close_and_refuses_the_closed_meeting(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    s = await seed(maker, status="live", votes=("draft",))
    async with maker() as closer, maker() as opener:
        meeting = await closer.scalar(
            select(Meeting).where(Meeting.id == s.meeting_id).with_for_update()
        )
        assert meeting is not None
        task = _spawn(
            VotingService(opener).open(s.vote_ids["draft"], now=datetime.now(UTC), actor="x")
        )
        await _blocked(task)
        meeting.status = "closed"
        await closer.commit()
        with pytest.raises(ConflictError) as ei:
            await task
        assert ei.value.code == "meeting_closed"
        await opener.rollback()
    async with maker() as session:
        vote = await session.get(Vote, s.vote_ids["draft"])
        assert vote is not None and vote.status == "draft"


async def test_close_waits_for_an_open_and_sees_the_open_vote(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    s = await seed(maker, status="live", votes=("draft",), protocol="draft")
    async with maker() as opener, maker() as closer:
        # The open takes the meeting lock first and holds it until its commit.
        await opener.scalar(
            select(Meeting.id).where(Meeting.id == s.meeting_id).with_for_update()
        )
        vote = await opener.get(Vote, s.vote_ids["draft"])
        assert vote is not None
        task = _spawn(
            MeetingService(closer).patch(
                s.meeting_id, MeetingPatch.model_validate({"status": "closed"}), admin()
            )
        )
        await _blocked(task)
        vote.status = "open"
        await opener.commit()
        with pytest.raises(ConflictError) as ei:
            await task
        assert ei.value.code == "open_vote"
        await closer.rollback()
    async with maker() as session:
        meeting = await session.get(Meeting, s.meeting_id)
        assert meeting is not None and meeting.status == "live"


async def test_remove_waits_for_an_open_and_keeps_the_item(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    s = await seed(maker, status="live", votes=("draft",))
    async with maker() as opener, maker() as remover:
        await opener.scalar(
            select(Meeting.id).where(Meeting.id == s.meeting_id).with_for_update()
        )
        vote = await opener.get(Vote, s.vote_ids["draft"])
        assert vote is not None
        task = _spawn(
            AgendaService(remover).remove(
                s.meeting_id, s.item_ids[0], actor=ADMIN_SUB, may_delete_votes=True
            )
        )
        await _blocked(task)
        vote.status = "open"
        await opener.commit()
        with pytest.raises(ConflictError) as ei:
            await task
        assert ei.value.code == "agenda_item_has_vote"
        await remover.rollback()


async def test_open_refuses_a_planned_meeting(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    s = await seed(maker, status="planned", votes=("draft",))
    async with maker() as session:
        with pytest.raises(ConflictError) as ei:
            await VotingService(session).open(
                s.vote_ids["draft"], now=datetime.now(UTC), actor="x"
            )
    assert ei.value.code == "meeting_not_started"


async def test_create_refuses_an_agenda_item_of_another_meeting(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """A removed agenda item, or one of another meeting, gets no new vote."""
    s = await seed(maker, status="live")
    other = await seed(maker, status="live")
    payload = VoteCreateInternal(
        config=VoteConfig.model_validate({"options": ["yes", "no"], "majorityRule": "simple"}),
        eligibleGroup=s.gremium_id,
        question="Q",
        eligibleCount=3,
    )
    async with maker() as session:
        with pytest.raises(NotFoundError):
            await VotingService(session).create_internal(
                None, payload, meeting_id=s.meeting_id, agenda_item_id=other.item_ids[0]
            )
