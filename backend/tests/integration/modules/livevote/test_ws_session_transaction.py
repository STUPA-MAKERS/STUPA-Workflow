"""The member live-vote socket ends its transaction after every cycle, real Postgres.

The socket keeps its request session for the whole meeting. A read that leaves its
transaction open holds a pool connection "idle in transaction" until the disconnect,
and the session (``expire_on_commit=False``) keeps sending the meeting state of its
first read. These tests run the connection on a real session and check both: no open
transaction after a state send or a cast, and a resync that sends the new state.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.connection import LiveVoteConnection
from app.modules.livevote.locks import InMemoryLocker
from app.modules.livevote.models import Meeting
from app.modules.livevote.service import MeetingService
from app.modules.voting.models import Ballot
from app.modules.voting.service import VotingService
from tests.integration.modules.livevote.conftest import seed

pytestmark = pytest.mark.integration


class _WS:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)


def _connection(
    session: AsyncSession, meeting_id: uuid.UUID, principal: Principal
) -> LiveVoteConnection:
    return LiveVoteConnection(
        _WS(),  # type: ignore[arg-type]
        meeting_id,
        beamer=False,
        principal=principal,
        meetings=MeetingService(session),
        voting=VotingService(session),
        broker=InMemoryBroker(),
        locker=InMemoryLocker(),
    )


async def test_resync_ends_the_transaction_and_sends_the_new_state(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    s = await seed(maker, status="planned")
    async with maker() as session:
        conn = _connection(session, s.meeting_id, Principal(sub="viewer"))
        await conn._send_state()
        assert session.in_transaction() is False
        assert conn.ws.sent[-1]["status"] == "planned"  # type: ignore[attr-defined]

        # Another request starts the meeting.
        async with maker() as other:
            meeting = await other.get(Meeting, s.meeting_id)
            assert meeting is not None
            meeting.status = "live"
            await other.commit()

        await conn._handle_message({"type": "subscribe"})
        assert session.in_transaction() is False
        assert conn.ws.sent[-1]["type"] == "meeting_state"  # type: ignore[attr-defined]
        assert conn.ws.sent[-1]["status"] == "live"  # type: ignore[attr-defined]


async def test_cast_ends_the_transaction(maker: async_sessionmaker[AsyncSession]) -> None:
    s = await seed(maker, status="live", votes=("open",))
    vote_id = s.vote_ids["open"]
    sub = f"voter-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        session.add(PrincipalRow(sub=sub, display_name="V", email=f"{sub}@x.de"))
        await session.commit()

    voter = Principal(sub=sub, groups={vote_group_key(s.gremium_id)})
    async with maker() as session:
        conn = _connection(session, s.meeting_id, voter)
        published: list[Any] = []

        async def _tally(vote: Any) -> None:
            published.append(vote)

        conn.publisher.vote_tally = _tally  # type: ignore[method-assign]
        await conn._handle_cast({"type": "cast", "voteId": str(vote_id), "choice": "yes"})
        assert [m for m in conn.ws.sent if m["type"] == "error"] == []  # type: ignore[attr-defined]
        assert session.in_transaction() is False
        assert len(published) == 1
        assert published[0].tally.voted == 1

        # A second cast gets the error frame and ends its transaction too.
        await conn._handle_cast({"type": "cast", "voteId": str(vote_id), "choice": "no"})
        assert conn.ws.sent[-1] == {"type": "error", "code": "already_voted"}  # type: ignore[attr-defined]
        assert session.in_transaction() is False

    async with maker() as session:
        count = await session.scalar(
            select(func.count()).select_from(Ballot).where(Ballot.vote_id == vote_id)
        )
        assert count == 1
