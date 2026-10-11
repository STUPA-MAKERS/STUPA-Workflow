"""A Gremium delete applies the rules of the meeting delete to its meetings, real Postgres.

The meeting row cascades with the Gremium, and the votes of a meeting only detach
(``vote.meeting_id`` SET NULL). Without the rules, a final protocol would go without
``meeting.delete_finalized``, an open vote would stay open without its meeting, and no
vote would get a ``vote_delete`` audit entry. The Gremium delete therefore runs the
meeting delete for each meeting first. A vote of the Gremium without a meeting stays,
but an open one refuses the delete.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.models import Gremium
from app.modules.admin.service import ConfigService
from app.modules.auth.principal import Principal
from app.modules.livevote.models import Meeting
from app.modules.protocol.models import Protocol
from app.modules.voting.models import Ballot, Vote
from app.shared.errors import ForbiddenError
from tests.integration.modules.livevote.conftest import CONFIG, audit_actions, seed

pytestmark = pytest.mark.integration


async def _standalone_vote(
    maker: async_sessionmaker[AsyncSession], gremium_id: uuid.UUID, status: str
) -> uuid.UUID:
    """Write a vote of the Gremium without a meeting."""
    async with maker() as session:
        vote = Vote(
            application_id=None,
            meeting_id=None,
            eligible_group=str(gremium_id),
            config=CONFIG,
            status=status,
            result="passed" if status == "closed" else None,
        )
        session.add(vote)
        await session.commit()
        return vote.id


async def test_gremium_delete_deletes_meetings_and_keeps_votes_without_a_meeting(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="closed", votes=("draft", "closed"), protocol="final")
    standalone = await _standalone_vote(maker, s.gremium_id, "closed")
    async with maker() as session:
        session.add(Ballot(vote_id=s.vote_ids["closed"], voter_sub="s1", choice="yes"))
        await session.commit()

    with TestClient(api) as client:
        resp = client.delete(f"/api/admin/gremien/{s.gremium_id}")
    assert resp.status_code == 204, resp.text

    async with maker() as session:
        assert await session.get(Gremium, s.gremium_id) is None
        assert await session.get(Meeting, s.meeting_id) is None
        assert await session.get(Protocol, s.protocol_id) is None
        for vote_id in s.vote_ids.values():
            assert await session.get(Vote, vote_id) is None
        kept = await session.get(Vote, standalone)
        assert kept is not None
        assert kept.status == "closed"
        ballots = await session.scalars(
            select(Ballot).where(Ballot.vote_id == s.vote_ids["closed"])
        )
        assert ballots.all() == []

    [meeting_entry] = await audit_actions(maker, target_id=s.meeting_id)
    assert meeting_entry.action == "meeting_delete"
    assert meeting_entry.data["reason"] == "gremium_deleted"
    assert meeting_entry.data["finalizedProtocol"] is True
    assert sorted(meeting_entry.data["deletedVoteIds"]) == sorted(
        str(v) for v in s.vote_ids.values()
    )
    for vote_id in s.vote_ids.values():
        [entry] = await audit_actions(maker, target_id=vote_id)
        assert entry.action == "vote_delete"
        assert entry.data["reason"] == "meeting_deleted"
    assert await audit_actions(maker, target_id=standalone) == []
    [gremium_entry] = await audit_actions(maker, target_id=s.gremium_id)
    assert gremium_entry.action == "config_change"


@pytest.mark.parametrize("where", ["meeting", "standalone"])
async def test_gremium_delete_with_an_open_vote_is_refused(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, where: str
) -> None:
    """An open vote, in a meeting or without one, stops the delete; nothing changes."""
    s = await seed(maker, status="live", votes=("open",) if where == "meeting" else ("draft",))
    if where == "standalone":
        await _standalone_vote(maker, s.gremium_id, "open")

    with TestClient(api) as client:
        resp = client.delete(f"/api/admin/gremien/{s.gremium_id}")
    assert resp.status_code == 409, resp.text
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["code"] == "open_vote"

    async with maker() as session:
        assert await session.get(Gremium, s.gremium_id) is not None
        assert await session.get(Meeting, s.meeting_id) is not None
        for vote_id in s.vote_ids.values():
            assert await session.get(Vote, vote_id) is not None
    assert await audit_actions(maker, target_id=s.meeting_id) == []
    assert await audit_actions(maker, target_id=s.gremium_id) == []


async def test_gremium_delete_with_a_final_protocol_needs_the_permission(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """``admin.gremien`` alone does not delete a final protocol."""
    s = await seed(maker, status="closed", votes=("closed",), protocol="final")
    gremien_admin = Principal(sub="gremien-admin", permissions={"admin.gremien"})
    async with maker() as session:
        with pytest.raises(ForbiddenError, match="delete_finalized") as err:
            await ConfigService(session).delete_gremium(s.gremium_id, gremien_admin)
    assert err.value.code == "meeting_finalized"

    async with maker() as session:
        assert await session.get(Gremium, s.gremium_id) is not None
        assert await session.get(Meeting, s.meeting_id) is not None
        assert await session.get(Vote, s.vote_ids["closed"]) is not None
    assert await audit_actions(maker, target_id=s.meeting_id) == []

    # A draft protocol needs no further right.
    draft = await seed(maker, status="closed", votes=("closed",), protocol="draft")
    async with maker() as session:
        await ConfigService(session).delete_gremium(draft.gremium_id, gremien_admin)
    async with maker() as session:
        assert await session.get(Gremium, draft.gremium_id) is None
        assert await session.get(Vote, draft.vote_ids["closed"]) is None
