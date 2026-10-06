"""O12: a meeting with an open vote does not close, and the close cancels the drafts.

The tests run on a real Postgres through the REST route ``PATCH /meetings/{id}``.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.livevote.models import Meeting
from app.modules.voting.models import Vote
from tests.integration.modules.livevote.conftest import audit_actions, seed

pytestmark = pytest.mark.integration


async def test_close_with_open_vote_is_refused(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, votes=("open", "draft"), protocol="draft")
    with TestClient(api) as client:
        resp = client.patch(f"/api/meetings/{s.meeting_id}", json={"status": "closed"})
    assert resp.status_code == 409, resp.text
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["code"] == "open_vote"
    async with maker() as session:
        meeting = await session.get(Meeting, s.meeting_id)
        draft = await session.get(Vote, s.vote_ids["draft"])
        assert meeting is not None and draft is not None
        assert meeting.status == "live"
        assert meeting.closed_at is None
        assert draft.status == "draft"
    assert await audit_actions(maker, target_id=s.meeting_id) == []


async def test_close_cancels_draft_votes_in_one_transaction(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, votes=("draft", "closed"), protocol="draft")
    with TestClient(api) as client:
        resp = client.patch(f"/api/meetings/{s.meeting_id}", json={"status": "closed"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "closed"
    assert body["closedAt"] is not None
    async with maker() as session:
        draft = await session.get(Vote, s.vote_ids["draft"])
        closed = await session.get(Vote, s.vote_ids["closed"])
        assert draft is not None and closed is not None
        assert draft.status == "cancelled"
        assert draft.closed_at is not None
        assert closed.status == "closed"
    cancel = await audit_actions(maker, target_id=s.vote_ids["draft"])
    assert [(e.action, e.data["reason"]) for e in cancel] == [("vote_cancel", "meeting_closed")]
    [update] = await audit_actions(maker, target_id=s.meeting_id)
    assert update.action == "meeting_update"
    assert update.data["changes"] == {"status": {"from": "live", "to": "closed"}}


@pytest.mark.parametrize(
    ("current", "target"),
    [("planned", "closed"), ("live", "planned"), ("closed", "live"), ("closed", "planned")],
)
async def test_invalid_status_transition(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, current: str, target: str
) -> None:
    """F9 and O13: the status runs only planned, live, closed."""
    s = await seed(maker, status=current)
    with TestClient(api) as client:
        resp = client.patch(f"/api/meetings/{s.meeting_id}", json={"status": target})
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "invalid_status_transition"
    async with maker() as session:
        meeting = await session.get(Meeting, s.meeting_id)
        assert meeting is not None
        assert meeting.status == current
