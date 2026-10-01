"""F22: an audit revert of a status change cancels the votes of the left state.

The application enters the vote state, a vote opens, and the audit log reverts the
status change. The application returns to the old state, the open vote becomes
`cancelled` with `closed_at`, and the publisher sends `vote_cancelled` (real Postgres).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.models import Application
from app.modules.audit.models import AuditEntry
from app.modules.config_revision.revert import RevertService
from app.modules.flow.service import FlowService
from app.modules.voting.models import Vote
from tests.integration.modules.voting.vote_support import (
    RecordingPublisher,
    add_vote,
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


async def test_revert_out_of_the_vote_state_cancels_its_votes(
    session: AsyncSession,
) -> None:
    flow = await seed_vote_flow(session, start="review")
    await FlowService(session).fire(flow.app_id, flow.transitions["start"], manager())
    entry_id = (
        await session.execute(
            select(AuditEntry.id)
            .where(
                AuditEntry.action == "status_change",
                AuditEntry.target_id == str(flow.app_id),
            )
            .order_by(AuditEntry.id.desc())
            .limit(1)
        )
    ).scalar_one()
    running = await add_vote(session, flow, opens_at=NOW)
    # A draft of the restored state stays.
    kept = await add_vote(session, flow, status="draft", opens_state="review")
    publisher = RecordingPublisher()

    await RevertService(session, publisher).revert(  # type: ignore[arg-type]
        entry_id, "admin", manager()
    )

    app = await session.get(Application, flow.app_id)
    assert app is not None
    await session.refresh(app)
    assert app.current_state_id == flow.states["review"]
    vote = await session.get(Vote, running)
    assert vote is not None
    await session.refresh(vote)
    assert vote.status == "cancelled"
    assert vote.closed_at is not None
    draft = await session.get(Vote, kept)
    assert draft is not None
    await session.refresh(draft)
    assert draft.status == "draft"
    assert publisher.cancelled == [running]

