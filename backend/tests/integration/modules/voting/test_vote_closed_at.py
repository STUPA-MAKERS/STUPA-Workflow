"""Z9/O10, F12 and A5 against a real Postgres.

`close` and `cancel` set `vote.closed_at`. `closes_at` stays the planned end of the
cast window. Open, close and cancel write audit entries with id references and
aggregates only. `GET /votes/{id}` (`get_scoped`) returns the real times and the own
ballot of the caller.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.voting.models import Vote
from app.modules.voting.service import VotingService
from tests.integration.modules.voting.vote_support import (
    add_vote,
    audit_actions,
    manager,
    seed_vote_flow,
    voter,
)

pytestmark = pytest.mark.integration

OPEN = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
WINDOW_END = OPEN + timedelta(days=2)


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def test_close_sets_closed_at_and_audits(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    vote_id = await add_vote(session, flow, status="draft")
    row = await session.get(Vote, vote_id)
    assert row is not None
    row.closes_at = WINDOW_END
    await session.commit()
    svc = VotingService(session)
    opened = await svc.open(vote_id, now=OPEN, actor="mgr")
    assert opened.opened_at == OPEN
    assert opened.closed_at is None
    await svc.cast(vote_id, voter("v1", flow), "yes", now=OPEN)
    await svc.cast(vote_id, voter("v2", flow), "no", now=OPEN)
    await svc.cast(vote_id, voter("v3", flow), "yes", now=OPEN)

    closed_at = OPEN + timedelta(minutes=12)
    out = await svc.close(vote_id, manager(), now=closed_at)
    assert out.closed_at == closed_at
    assert out.branch_fired is True

    await session.refresh(row)
    assert row.closed_at == closed_at
    assert row.closes_at == WINDOW_END  # the window end is a different column

    entries = await audit_actions(session, vote_id)
    assert [e.action for e in entries] == ["vote_open", "vote_close"]
    close = entries[1].data
    assert close["result"] == "passed"
    assert close["counts"] == {"yes": 2, "no": 1, "abstain": 0}
    assert close["applicationId"] == str(flow.app_id)
    # Aggregates only: no voter sub anywhere in the entry.
    assert "v1" not in str(close) and "v2" not in str(close)


async def test_cancel_sets_closed_at_and_audits(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    vote_id = await add_vote(session, flow, opens_at=OPEN)
    at = OPEN + timedelta(minutes=3)
    out = await VotingService(session).cancel(vote_id, now=at, actor="mgr")
    assert out.status == "cancelled"
    assert out.closed_at == at
    entries = await audit_actions(session, vote_id)
    assert [e.action for e in entries] == ["vote_cancel"]
    assert entries[0].actor == "mgr"
    assert entries[0].data["reason"] == "manual"


async def test_get_scoped_returns_own_ballot(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    open_id = await add_vote(session, flow, opens_at=OPEN)
    secret_id = await add_vote(session, flow, opens_at=OPEN, secret=True)
    svc = VotingService(session)
    me = voter("me", flow)
    await svc.cast(open_id, me, "no", now=OPEN)
    await svc.cast(secret_id, me, "yes", now=OPEN)

    mine = await svc.get_scoped(open_id, me)
    assert mine.my_ballot is not None
    assert (mine.my_ballot.cast, mine.my_ballot.choice) == (True, "no")
    assert mine.opened_at == OPEN
    assert mine.majority_rule == "simple"
    assert mine.represented_cast is False

    secret = await svc.get_scoped(secret_id, me)
    assert secret.my_ballot is not None
    assert (secret.my_ballot.cast, secret.my_ballot.choice) == (True, None)

    other = await svc.get_scoped(open_id, voter("other", flow))
    assert other.my_ballot is not None
    assert other.my_ballot.cast is False
