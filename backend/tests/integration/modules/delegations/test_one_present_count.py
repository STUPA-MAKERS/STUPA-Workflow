"""One count of present members in the head, the vote and the protocol of a meeting.

§F/meetings/meetings/000946: the count is the count of the quorum. A member with a
voting right and the status `present` counts, and each pool substitute on a seat. A
person counts one time only. A member without a voting right, a former member and a
guest do not count. The close of the meeting fixes the count.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.delegations.models import MeetingDelegation
from app.modules.meetings.models import Meeting, MeetingAttendance
from app.modules.meetings.present import Present, meeting_present, present_count
from app.modules.protocol.service import ProtocolService
from app.modules.voting.models import Vote
from app.shared.config_schemas import VoteConfig
from tests.integration.modules.delegations.conftest import (
    act,
    gremium,
    meeting,
    member,
    person,
)

pytestmark = pytest.mark.integration

MOTION = VoteConfig.model_validate(
    {"options": ["yes", "no", "abstain"], "majorityRule": "simple", "secret": True}
).model_dump(by_alias=True)


async def _seed(maker: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a live meeting whose one count is 3.

    Anna and Ben are present members with a voting right. Ben also holds the pool seat
    of Dora and still counts one time. Sam holds the pool seat of Cem and is no member.
    Rita is a present member without a voting right, Fritz a present former member.
    """
    gremium_id = await gremium(maker)
    ids = {name: (await member(maker, gremium_id, name))[1] for name in ("Anna", "Ben")}
    ids |= {name: (await member(maker, gremium_id, name))[1] for name in ("Cem", "Dora")}
    ids["Rita"] = (await member(maker, gremium_id, "Rita", permissions=()))[1]
    ids["Fritz"] = (await person(maker, "Fritz"))[1]
    ids["Sam"] = (await person(maker, "Sam"))[1]
    meeting_id = await meeting(maker, gremium_id, status="live")
    async with maker() as session:
        session.add_all(
            MeetingAttendance(meeting_id=meeting_id, principal_id=ids[name], status="present")
            for name in ("Anna", "Ben", "Rita", "Fritz")
        )
        session.add_all(
            MeetingDelegation(
                meeting_id=meeting_id,
                gremium_id=gremium_id,
                delegator_principal_id=ids[member_name],
                delegate_principal_id=ids[holder],
                delegate_voting=True,
                via_pool=True,
                created_by="lead",
            )
            for member_name, holder in (("Cem", "Sam"), ("Dora", "Ben"))
        )
        session.add(
            Vote(
                application_id=None,
                meeting_id=meeting_id,
                eligible_group=str(gremium_id),
                config=MOTION,
                kind="motion",
                status="open",
            )
        )
        await session.commit()
    return gremium_id, meeting_id


async def test_the_head_the_vote_and_the_protocol_show_one_count(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/meetings/000946: 2 present members and 1 pool seat give 3 everywhere."""
    _, meeting_id = await _seed(maker)
    act(api, None)
    with TestClient(api) as client:
        head = client.get(f"/api/meetings/{meeting_id}").json()
        rows = client.get(f"/api/meetings/{meeting_id}/attendance").json()
    async with maker() as session:
        counted = await present_count(session, meeting_id)
        row = await session.get(Meeting, meeting_id)
        assert row is not None
        header = await ProtocolService(session)._header_meta(row, public=True)
    present_voters = [r for r in rows if r["status"] == "present" and r["canVote"]]
    assert counted == Present(members=2, seats=1)
    assert head["presentCount"] is None
    assert len(present_voters) + head["presentSeats"] == 3
    assert [vote["present"] for vote in head["votes"]] == [3]
    assert header.present_count == 3


async def test_the_close_fixes_the_count(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/meetings/000946: a closed meeting keeps the count of its close."""
    _, meeting_id = await _seed(maker)
    async with maker() as session:
        row = await session.get(Meeting, meeting_id)
        assert row is not None
        row.status, row.present_count, row.eligible_count = "closed", 7, 9
        await session.commit()
        assert await meeting_present(session, row) == 7
    act(api, None)
    with TestClient(api) as client:
        head = client.get(f"/api/meetings/{meeting_id}").json()
    assert (head["presentCount"], head["eligibleCount"], head["presentSeats"]) == (7, 9, 0)
