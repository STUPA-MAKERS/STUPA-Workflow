"""F21: a meeting delete keeps its votes and ballots, also with a final protocol.

Before the fix ``vote.agenda_item_id`` had ``ON DELETE CASCADE``. The meeting delete
cascaded through the agenda items to the votes, their ballots and their protocol
references, although ``vote.meeting_id`` is ``SET NULL`` and the docstring promised
that the votes survive.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.livevote.models import Meeting
from app.modules.protocol.models import Protocol, ProtocolVoteRef
from app.modules.voting.models import Ballot, Vote
from tests.integration.modules.livevote.conftest import audit_actions, seed

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("protocol", ["draft", "final"])
async def test_meeting_delete_keeps_votes_and_ballots(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, protocol: str
) -> None:
    s = await seed(maker, status="closed", votes=("closed", "cancelled"), protocol=protocol)
    closed_id = s.vote_ids["closed"]
    async with maker() as session:
        session.add(Ballot(vote_id=closed_id, voter_sub="s1", choice="yes"))
        session.add(Ballot(vote_id=closed_id, voter_sub="s2", choice="no"))
        assert s.protocol_id is not None
        session.add(ProtocolVoteRef(protocol_id=s.protocol_id, vote_id=closed_id))
        await session.commit()

    with TestClient(api) as client:
        resp = client.delete(f"/api/meetings/{s.meeting_id}")
    assert resp.status_code == 204, resp.text

    async with maker() as session:
        assert await session.get(Meeting, s.meeting_id) is None
        for vote_id in s.vote_ids.values():
            vote = await session.get(Vote, vote_id)
            assert vote is not None
            # Both references are detached, the record stays.
            assert vote.meeting_id is None
            assert vote.agenda_item_id is None
        closed = await session.get(Vote, closed_id)
        assert closed is not None
        assert (closed.status, closed.result) == ("closed", "passed")
        ballots = await session.scalar(
            select(func.count()).select_from(Ballot).where(Ballot.vote_id == closed_id)
        )
        assert ballots == 2
        # The protocol and its vote references go with the meeting (CASCADE). The
        # vote itself stays.
        assert await session.get(Protocol, s.protocol_id) is None
        refs = await session.scalar(
            select(func.count()).select_from(ProtocolVoteRef).where(
                ProtocolVoteRef.vote_id == closed_id
            )
        )
        assert refs == 0
    [entry] = await audit_actions(maker, target_id=s.meeting_id)
    assert entry.action == "meeting_delete"
    assert entry.data["finalizedProtocol"] is (protocol == "final")
