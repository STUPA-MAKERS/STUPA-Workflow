"""A meeting delete deletes all votes of the meeting (replaces F21), real Postgres.

The delete takes every vote of the meeting with it, in any status (draft, cancelled,
closed, secret, with guests), together with the ballots, the secret ballots, the voted
markers and the protocol references. An open vote blocks the delete (409
``open_vote``). An application that such a vote decided keeps its status, and its
timeline shows the vote as deleted. The audit names the votes by id and count, never a
choice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.applications.models import Application, StatusEvent
from app.modules.applications.service import ApplicationsService
from app.modules.livevote.models import Meeting, MeetingGuest
from app.modules.livevote.service import MeetingService
from app.modules.protocol.models import Protocol, ProtocolVoteRef
from app.modules.voting.models import Ballot, SecretBallot, Vote, VotedMarker
from app.modules.voting.service import VotingService, guest_voter_sub
from tests.integration.modules.livevote.conftest import CONFIG, admin, audit_actions, seed
from tests.integration.modules.voting.vote_support import (
    add_meeting,
    add_vote,
    manager,
    seed_vote_flow,
    voter,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
SECRET_CONFIG = {**CONFIG, "secret": True}


async def _count(session: AsyncSession, model: type, vote_ids: list[uuid.UUID]) -> int:
    return (
        await session.scalar(
            select(func.count()).select_from(model).where(model.vote_id.in_(vote_ids))  # type: ignore[attr-defined]
        )
    ) or 0


@pytest.mark.parametrize("protocol", ["draft", "final"])
async def test_meeting_delete_deletes_every_vote_with_its_ballots(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, protocol: str
) -> None:
    s = await seed(
        maker, status="closed", votes=("draft", "cancelled", "closed"), protocol=protocol
    )
    async with maker() as session:
        # A closed secret vote: identity and choice live in two tables.
        secret = Vote(
            meeting_id=s.meeting_id,
            agenda_item_id=s.item_ids[0],
            eligible_group=str(s.gremium_id),
            config=SECRET_CONFIG,
            status="closed",
            result="rejected",
        )
        session.add(secret)
        guest = MeetingGuest(meeting_id=s.meeting_id, seq=1, status="admitted", requested_at=NOW)
        session.add(guest)
        await session.flush()
        closed_id = s.vote_ids["closed"]
        session.add(Ballot(vote_id=closed_id, voter_sub="s1", choice="yes"))
        session.add(Ballot(vote_id=closed_id, voter_sub="s2", choice="no"))
        # A guest ballot of the public meeting (#17).
        session.add(Ballot(vote_id=closed_id, voter_sub=guest_voter_sub(guest.id), choice="yes"))
        session.add(VotedMarker(vote_id=secret.id, voter_sub="s1"))
        session.add(SecretBallot(vote_id=secret.id, choice="no"))
        assert s.protocol_id is not None
        session.add(ProtocolVoteRef(protocol_id=s.protocol_id, vote_id=closed_id))
        session.add(ProtocolVoteRef(protocol_id=s.protocol_id, vote_id=secret.id))
        await session.commit()
        secret_id = secret.id
    vote_ids = [*s.vote_ids.values(), secret_id]

    with TestClient(api) as client:
        resp = client.delete(f"/api/meetings/{s.meeting_id}")
    assert resp.status_code == 204, resp.text

    async with maker() as session:
        assert await session.get(Meeting, s.meeting_id) is None
        assert await session.get(Protocol, s.protocol_id) is None
        for vote_id in vote_ids:
            assert await session.get(Vote, vote_id) is None
        for model in (Ballot, SecretBallot, VotedMarker, ProtocolVoteRef):
            assert await _count(session, model, vote_ids) == 0

    [entry] = await audit_actions(maker, target_id=s.meeting_id)
    assert entry.action == "meeting_delete"
    assert entry.data["finalizedProtocol"] is (protocol == "final")
    assert entry.data["deletedVotes"] == 4
    assert sorted(entry.data["deletedVoteIds"]) == sorted(str(v) for v in vote_ids)
    for vote_id in vote_ids:
        [deleted] = await audit_actions(maker, target_id=vote_id)
        assert deleted.action == "vote_delete"
        assert deleted.data["reason"] == "meeting_deleted"
        # No choice, no voter, no guest in any audit entry of the delete.
        for text in ("yes", "s1", "s2", "guest:"):
            assert text not in str(deleted.data)
            assert text not in str(entry.data)


async def test_meeting_delete_without_votes_audits_zero(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="planned")
    with TestClient(api) as client:
        resp = client.delete(f"/api/meetings/{s.meeting_id}")
    assert resp.status_code == 204, resp.text
    [entry] = await audit_actions(maker, target_id=s.meeting_id)
    assert entry.data["deletedVotes"] == 0
    assert entry.data["deletedVoteIds"] == []


async def test_meeting_delete_with_open_vote_is_refused(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """An open vote blocks the delete; the meeting and all votes stay."""
    s = await seed(maker, status="live", votes=("open", "draft", "closed"), protocol="draft")
    with TestClient(api) as client:
        resp = client.delete(f"/api/meetings/{s.meeting_id}")
    assert resp.status_code == 409, resp.text
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["code"] == "open_vote"
    async with maker() as session:
        assert await session.get(Meeting, s.meeting_id) is not None
        for status, vote_id in s.vote_ids.items():
            vote = await session.get(Vote, vote_id)
            assert vote is not None
            assert vote.status == status
            assert vote.meeting_id == s.meeting_id
    assert await audit_actions(maker, target_id=s.meeting_id) == []
    for vote_id in s.vote_ids.values():
        assert await audit_actions(maker, target_id=vote_id) == []


async def test_application_decided_by_a_deleted_vote_keeps_its_status(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The application stays approved; its timeline names the vote as deleted."""
    async with maker() as session:
        flow = await seed_vote_flow(session)
        meeting_id = await add_meeting(session, flow.gremium_id)
        vote_id = await add_vote(session, flow, status="draft")
        svc = VotingService(session)
        await svc.open(vote_id, now=NOW, actor="mgr")
        for sub in ("v1", "v2"):
            await svc.cast(vote_id, voter(sub, flow), "yes", now=NOW)
        closed = await svc.close(vote_id, manager(), now=NOW)
        assert closed.branch_fired is True
        # The vote belongs to the meeting: the meeting delete takes it along.
        row = await session.get(Vote, vote_id)
        assert row is not None
        row.meeting_id = meeting_id
        await session.commit()

        apps = ApplicationsService(session)
        before = await apps.timeline(flow.app_id)
        [branch] = [e for e in before if e.note == "vote:passed"]
        assert branch.vote_id == vote_id
        assert branch.vote_deleted is False
        # The applicant cannot open the vote: no link in that view.
        applicant = await apps.timeline(flow.app_id, applicant_view=True)
        assert [e.vote_id for e in applicant if e.note == "vote:passed"] == [None]

        await MeetingService(session).delete(meeting_id, admin())

    async with maker() as session:
        assert await session.get(Vote, vote_id) is None
        application = await session.get(Application, flow.app_id)
        assert application is not None
        assert application.current_state_id == flow.states["approved"]
        events = (
            await session.scalars(
                select(StatusEvent).where(StatusEvent.application_id == flow.app_id)
            )
        ).all()
        assert all(e.vote_id is None for e in events)
        after = await ApplicationsService(session).timeline(flow.app_id)
        assert [e.to_state_id for e in after] == [e.to_state_id for e in before]
        [branch] = [e for e in after if e.note == "vote:passed"]
        assert branch.vote_id is None
        assert branch.vote_deleted is True
        # Only the branch event names a vote.
        assert [e.vote_deleted for e in after].count(True) == 1
