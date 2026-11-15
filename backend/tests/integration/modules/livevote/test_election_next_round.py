"""The next Wahlgang of an election by the majority of the members.

``POST /api/votes/{id}/next-round`` creates the draft of the second and of the third
Wahlgang on the same agenda item. The third has the two strongest candidates, and the
lot gives a tied place (§F/meetings/voting/000971).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.voting.models import Vote
from tests.integration.modules.livevote.conftest import Seed, audit_actions, seed

pytestmark = pytest.mark.integration

CANDIDATES = [{"id": f"c{n}", "name": f"Person {n}"} for n in (1, 2, 3)]
CONFIG = {
    "seats": 1,
    "candidates": CANDIDATES,
    "secret": True,
    "majorityRule": "members_majority",
}


async def _closed(
    maker: async_sessionmaker[AsyncSession],
    s: Seed,
    counts: dict[str, int],
    *,
    result: str = "no_majority",
    round_: int = 1,
    parent: uuid.UUID | None = None,
) -> uuid.UUID:
    """Write a closed Wahlgang with a stored result."""
    async with maker() as session:
        vote = Vote(
            kind="election",
            application_id=None,
            meeting_id=s.meeting_id,
            agenda_item_id=s.item_ids[0],
            eligible_group=str(s.gremium_id),
            question="Vorsitz",
            config=CONFIG,
            eligible_count=9,
            status="closed",
            result=result,
            round=round_,
            parent_vote_id=parent,
            election_result={"counts": counts, "ballots": sum(counts.values()), "elected": []},
        )
        session.add(vote)
        await session.commit()
        return vote.id


async def test_three_rounds_then_the_lot(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live")
    first = await _closed(maker, s, {"c1": 3, "c2": 2, "c3": 2})
    with TestClient(api) as client:
        second = client.post(f"/api/votes/{first}/next-round")
        assert second.status_code == 201, second.text
        body = second.json()
        assert body["status"] == "draft"
        assert body["round"] == 2
        assert body["parentVoteId"] == str(first)
        assert body["agendaItemId"] == str(s.item_ids[0])
        assert [c["id"] for c in body["election"]["candidates"]] == ["c1", "c2", "c3"]
        again = client.post(f"/api/votes/{first}/next-round")
        assert again.status_code == 409
        assert again.json()["code"] == "next_round_exists"

        closed_second = await _closed(maker, s, {"c1": 3, "c2": 2, "c3": 2}, round_=2, parent=first)
        third = client.post(f"/api/votes/{closed_second}/next-round")
        assert third.status_code == 201, third.text
        standing = [c["id"] for c in third.json()["election"]["candidates"]]
        assert third.json()["round"] == 3
        assert len(standing) == 2
        assert standing[0] == "c1"
        assert standing[1] in {"c2", "c3"}

        closed_third = await _closed(maker, s, {"c1": 2, "c2": 2}, round_=3, parent=closed_second)
        fourth = client.post(f"/api/votes/{closed_third}/next-round")
        assert fourth.status_code == 409
        assert fourth.json()["code"] == "no_next_round"

    async with maker() as session:
        stored = await session.get(Vote, closed_second)
    assert stored is not None
    lot = stored.election_result["nextRoundLot"]
    assert lot["among"] == ["c2", "c3"]
    assert lot["drawn"] == [standing[1]]
    actions = [a.action for a in await audit_actions(maker, target_id=closed_second)]
    assert "vote_lot_drawn" in actions


async def test_next_round_needs_a_missed_members_majority(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live")
    elected = await _closed(maker, s, {"c1": 6, "c2": 1, "c3": 0}, result="elected")
    rejected = await _closed(maker, s, {"c1": 1, "c2": 0, "c3": 0}, result="rejected")
    with TestClient(api) as client:
        for vote_id in (elected, rejected, s.vote_ids.get("closed")):
            if vote_id is None:
                continue
            resp = client.post(f"/api/votes/{vote_id}/next-round")
            assert resp.status_code == 409, resp.text
            assert resp.json()["code"] == "no_next_round"


async def test_next_round_needs_a_live_meeting(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="closed")
    first = await _closed(maker, s, {"c1": 3, "c2": 2, "c3": 2})
    with TestClient(api) as client:
        resp = client.post(f"/api/votes/{first}/next-round")
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "meeting_closed"
