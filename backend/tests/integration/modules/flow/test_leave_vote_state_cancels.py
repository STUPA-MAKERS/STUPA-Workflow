"""F19: a state change out of a vote state cancels the votes of the application.

A transition without a branch and a forced status move the open AND the draft votes to
`cancelled`, set `closed_at` and write `vote_cancel`. Only the drafts of the state that
the application leaves go. A draft of another state stays, and a draft without
`opens_state_id` survives the transition into the vote state. After the commit the
publisher sends `vote_cancelled` for each cancelled vote (real Postgres).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.flow.service import FlowService
from app.modules.voting.models import Vote
from tests.integration.modules.voting.vote_support import (
    RecordingPublisher,
    add_meeting,
    add_vote,
    audit_actions,
    manager,
    seed_vote_flow,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _status(session: AsyncSession, vote_id) -> tuple[str, datetime | None]:  # noqa: ANN001
    vote = await session.get(Vote, vote_id)
    assert vote is not None
    await session.refresh(vote)
    return vote.status, vote.closed_at


async def test_manual_exit_cancels_open_and_draft_votes(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    meeting_id = await add_meeting(session, flow.gremium_id)
    running = await add_vote(session, flow, meeting_id=meeting_id, opens_at=NOW)
    draft = await add_vote(session, flow, status="draft", opens_state="voting")
    # A draft for the state the application enters stays.
    kept = await add_vote(session, flow, status="draft", opens_state="review")
    closed = await add_vote(session, flow, status="closed")
    publisher = RecordingPublisher()

    await FlowService(session, publisher=publisher).fire(  # type: ignore[arg-type]
        flow.app_id, flow.transitions["abort"], manager()
    )

    for vote_id in (running, draft):
        status, closed_at = await _status(session, vote_id)
        assert status == "cancelled"
        assert closed_at is not None
        entries = await audit_actions(session, vote_id)
        assert [e.action for e in entries] == ["vote_cancel"]
        assert entries[0].data["reason"] == "state_left"
        assert entries[0].actor == "mgr"
    assert await _status(session, kept) == ("draft", None)
    assert (await _status(session, closed))[0] == "closed"
    assert sorted(map(str, publisher.cancelled)) == sorted(map(str, (running, draft)))


async def test_force_status_cancels_open_and_draft_votes(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    running = await add_vote(session, flow, opens_at=NOW)
    draft = await add_vote(session, flow, status="draft")
    publisher = RecordingPublisher()

    await FlowService(session, publisher=publisher).force_status(  # type: ignore[arg-type]
        flow.app_id, flow.states["approved"], manager(), note="admin override"
    )

    for vote_id in (running, draft):
        status, closed_at = await _status(session, vote_id)
        assert status == "cancelled"
        assert closed_at is not None
    assert set(publisher.cancelled) == {running, draft}


async def test_branch_exit_cancels_nothing(session: AsyncSession) -> None:
    """The vote result branch leaves the other votes alone: close() owns the vote."""
    flow = await seed_vote_flow(session)
    other = await add_vote(session, flow, status="draft")
    publisher = RecordingPublisher()
    flow_svc = FlowService(session, publisher=publisher)  # type: ignore[arg-type]
    await flow_svc.fire_branch(flow.app_id, "pass", manager())
    assert await _status(session, other) == ("draft", None)
    assert publisher.cancelled == []


async def test_unbound_draft_survives_the_entry_into_the_vote_state(
    session: AsyncSession,
) -> None:
    """A draft without opens_state_id, made before the vote state, stays on A -> V."""
    flow = await seed_vote_flow(session, start="review")
    draft = await add_vote(session, flow, status="draft")
    later = await add_vote(session, flow, status="draft", opens_state="voting")
    publisher = RecordingPublisher()

    await FlowService(session, publisher=publisher).fire(  # type: ignore[arg-type]
        flow.app_id, flow.transitions["start"], manager()
    )

    assert await _status(session, draft) == ("draft", None)
    assert await _status(session, later) == ("draft", None)
    assert await audit_actions(session, draft) == []
    assert publisher.cancelled == []


async def test_draft_for_another_state_survives_a_force(session: AsyncSession) -> None:
    """A forced exit out of a normal state keeps a draft that belongs to the vote state."""
    flow = await seed_vote_flow(session, start="review")
    draft = await add_vote(session, flow, status="draft", opens_state="voting")
    unbound = await add_vote(session, flow, status="draft")
    publisher = RecordingPublisher()

    await FlowService(session, publisher=publisher).force_status(  # type: ignore[arg-type]
        flow.app_id, flow.states["approved"], manager(), note="admin override"
    )

    assert await _status(session, draft) == ("draft", None)
    assert await _status(session, unbound) == ("draft", None)
    assert publisher.cancelled == []
