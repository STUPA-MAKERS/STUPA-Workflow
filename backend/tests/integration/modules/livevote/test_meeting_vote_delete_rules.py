"""O24: a meeting vote is deletable only while the meeting is planned or live.

Every delete writes ``vote_delete``. After the close the vote is part of the record and
the route answers 409 ``meeting_closed``. An open or closed vote is part of the record
too (409 ``vote_not_deletable``), so its agenda item stays (O25).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.livevote.models import MeetingAgendaItem
from app.modules.voting.models import Vote
from tests.integration.modules.livevote.conftest import ADMIN_SUB, audit_actions, seed

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("meeting", "vote"), [("planned", "draft"), ("live", "draft"), ("live", "cancelled")]
)
async def test_delete_meeting_vote_is_audited(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, meeting: str, vote: str
) -> None:
    s = await seed(maker, status=meeting, votes=(vote,))
    vote_id = s.vote_ids[vote]
    with TestClient(api) as client:
        resp = client.delete(f"/api/meetings/{s.meeting_id}/votes/{vote_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["votes"] == []
    async with maker() as session:
        assert await session.get(Vote, vote_id) is None
    [entry] = await audit_actions(maker, target_id=vote_id)
    assert entry.action == "vote_delete"
    assert entry.actor == ADMIN_SUB
    assert entry.data["meetingId"] == str(s.meeting_id)
    assert entry.data["agendaItemId"] == str(s.item_ids[0])
    assert entry.data["status"] == vote


async def test_delete_meeting_vote_after_close_is_refused(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="closed", votes=("closed",), protocol="final")
    vote_id = s.vote_ids["closed"]
    with TestClient(api) as client:
        resp = client.delete(f"/api/meetings/{s.meeting_id}/votes/{vote_id}")
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "meeting_closed"
    async with maker() as session:
        assert await session.get(Vote, vote_id) is not None
    assert await audit_actions(maker, target_id=vote_id) == []


@pytest.mark.parametrize("vote", ["open", "closed"])
async def test_delete_open_or_closed_meeting_vote_is_refused(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, vote: str
) -> None:
    """Two deletes do not get around O25: the vote stays, so the agenda item stays."""
    s = await seed(maker, status="live", votes=(vote,))
    vote_id = s.vote_ids[vote]
    with TestClient(api) as client:
        resp = client.delete(f"/api/meetings/{s.meeting_id}/votes/{vote_id}")
        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] == "vote_not_deletable"
        top = client.delete(f"/api/meetings/{s.meeting_id}/agenda/{s.item_ids[0]}")
    assert top.status_code == 409, top.text
    assert top.json()["code"] == "agenda_item_has_vote"
    async with maker() as session:
        assert await session.get(Vote, vote_id) is not None
        assert await session.get(MeetingAgendaItem, s.item_ids[0]) is not None
    assert await audit_actions(maker, target_id=vote_id) == []
