"""F25: the protocol embeds only the votes of its own meeting.

A vote of another meeting, maybe of another gremium, or a vote without a meeting
gives 422 `vote_not_in_meeting`. Nothing is embedded then. A vote of the meeting
embeds as before.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.protocol.models import ProtocolVoteRef
from app.modules.voting.models import Vote
from tests.integration.modules.livevote.conftest import CONFIG, seed

pytestmark = pytest.mark.integration


async def _refs(maker: async_sessionmaker[AsyncSession]) -> int:
    async with maker() as session:
        return int(await session.scalar(select(func.count()).select_from(ProtocolVoteRef)) or 0)


async def test_embed_refuses_a_vote_of_another_meeting(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    own = await seed(maker, status="live", items=1, votes=("closed",), protocol="draft")
    other = await seed(maker, status="live", items=1, votes=("closed",))
    async with maker() as session:
        loose = Vote(
            application_id=None,
            meeting_id=None,
            eligible_group=str(own.gremium_id),
            config=CONFIG,
            status="closed",
            result="passed",
        )
        session.add(loose)
        await session.commit()
    url = f"/api/protocols/{own.protocol_id}/votes"
    before = await _refs(maker)
    with TestClient(api) as client:
        foreign = client.post(url, json={"voteIds": [str(other.vote_ids["closed"])]})
        mixed = client.post(
            url, json={"voteIds": [str(own.vote_ids["closed"]), str(loose.id)]}
        )
        assert await _refs(maker) == before
        good = client.post(url, json={"voteIds": [str(own.vote_ids["closed"])]})
    for resp in (foreign, mixed):
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "vote_not_in_meeting"
    assert good.status_code == 200, good.text
    assert "[!abstimmung]" in good.json()["markdown"]
    assert await _refs(maker) == before + 1
