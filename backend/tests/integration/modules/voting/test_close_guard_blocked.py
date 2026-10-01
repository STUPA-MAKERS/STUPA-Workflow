"""F20: a blocked result branch does not block the vote close (real Postgres).

The close stages the tally, the result, `status=closed` and `closed_at`. It stages the
`pass` or `fail` transition in a SAVEPOINT and commits ONCE. When the guard of the
transition fails, or the vote state has no such transition, only the SAVEPOINT rolls
back: the vote stays closed, the audit log holds `vote_branch_blocked`, there is no
409, and the application stays in its state. The cron does not pick the vote again.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.models import Application
from app.modules.deadlines.service import DeadlineService
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


class _CommitCounter:
    def __init__(self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0
        real = session.commit

        async def _commit() -> None:
            self.count += 1
            await real()

        monkeypatch.setattr(session, "commit", _commit)


async def _assert_blocked(
    session: AsyncSession, vote_id, app_id, voting_state, branch: str, reason: str  # noqa: ANN001
) -> None:
    vote = await session.get(Vote, vote_id)
    assert vote is not None
    await session.refresh(vote)
    assert vote.status == "closed"
    assert vote.closed_at is not None
    assert vote.result_branch_transition_id is None
    app = await session.get(Application, app_id)
    assert app is not None
    await session.refresh(app)
    assert app.current_state_id == voting_state
    entries = await audit_actions(session, vote_id)
    assert [e.action for e in entries] == ["vote_close", "vote_branch_blocked"]
    assert entries[1].data["branch"] == branch
    assert entries[1].data["reason"] == reason
    # The application has no status change: the branch rolled back.
    app_actions = [e.action for e in await audit_actions(session, app_id)]
    assert "status_change" not in app_actions


async def test_guard_failure_closes_the_vote(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow = await seed_vote_flow(session, pass_guard={"hasField": "missing"})
    vote_id = await add_vote(session, flow, opens_at=NOW)
    svc = VotingService(session)
    await svc.cast(vote_id, voter("v1", flow), "yes", now=NOW)
    commits = _CommitCounter(session, monkeypatch)

    out = await svc.close(vote_id, manager())
    assert out.result == "passed"
    assert out.branch_fired is False
    assert out.fired_transition_id is None
    assert commits.count == 1
    await _assert_blocked(
        session, vote_id, flow.app_id, flow.states["voting"], "pass", "guard_failed"
    )


async def test_missing_branch_closes_the_vote(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session, with_fail=False)
    vote_id = await add_vote(session, flow, opens_at=NOW)
    svc = VotingService(session)
    await svc.cast(vote_id, voter("v1", flow), "no", now=NOW)

    out = await svc.close(vote_id, manager())
    assert out.result == "rejected"
    assert out.branch_fired is False
    await _assert_blocked(
        session, vote_id, flow.app_id, flow.states["voting"], "fail", "no_branch"
    )


async def test_cron_does_not_retry_a_blocked_close(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session, with_fail=False)
    vote_id = await add_vote(session, flow, opens_at=NOW)
    row = await session.get(Vote, vote_id)
    assert row is not None
    row.closes_at = NOW + timedelta(minutes=5)
    await session.commit()
    later = NOW + timedelta(hours=1)
    assert vote_id in await DeadlineService(session).due_open_vote_ids(later)

    out = await VotingService(session).close(vote_id, manager(), now=later)
    assert out.branch_fired is False
    assert vote_id not in await DeadlineService(session).due_open_vote_ids(later)


async def test_fired_branch_commits_once(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow = await seed_vote_flow(session)
    vote_id = await add_vote(session, flow, opens_at=NOW)
    svc = VotingService(session)
    await svc.cast(vote_id, voter("v1", flow), "yes", now=NOW)
    commits = _CommitCounter(session, monkeypatch)

    out = await svc.close(vote_id, manager())
    assert out.branch_fired is True
    assert out.new_state_id == flow.states["approved"]
    assert commits.count == 1
    vote = await session.get(Vote, vote_id)
    assert vote is not None
    await session.refresh(vote)
    assert vote.result_branch_transition_id == flow.transitions["pass"]
