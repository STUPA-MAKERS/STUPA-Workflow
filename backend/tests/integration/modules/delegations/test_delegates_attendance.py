"""The delegates in the attendance list, in the one count and in the protocol.

* §F/meetings/delegations/003150: the roster has a row for a delegate who is no member,
  with the represented members. The lead sets it, the delegate reports it.
* §F/meetings/delegations/003151: a present delegate counts once in the one count.
* §F/meetings/delegations/003152: a ballot of a delegate marks the delegate present, and
  a pool seat without a record reads present.
* §F/meetings/protocols/003153: the protocol names the delegate with the member.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.delegations.models import MeetingDelegation
from app.modules.meetings.models import Meeting, MeetingAttendance
from app.modules.meetings.present import Present, present_count
from app.modules.protocol.service import ProtocolService
from app.modules.voting.models import Vote
from app.shared.config_schemas import VoteConfig
from tests.integration.modules.delegations.conftest import act, gremium, meeting, member, person

pytestmark = pytest.mark.integration

MOTION = VoteConfig.model_validate(
    {"options": ["yes", "no", "abstain"], "majorityRule": "simple", "secret": True}
).model_dump(by_alias=True)


class _World:
    def __init__(self) -> None:
        self.gremium_id = uuid.uuid4()
        self.meeting_id = uuid.uuid4()
        self.subs: dict[str, str] = {}
        self.ids: dict[str, uuid.UUID] = {}


async def _world(maker: async_sessionmaker[AsyncSession], *, pool: bool = False) -> _World:
    """Seed a live meeting: Anna is present, Max and Mia gave their vote to Lea.

    Lea is no member. With ``pool`` her delegations are pool seats.
    """
    w = _World()
    w.gremium_id = await gremium(maker)
    for name in ("Anna", "Max", "Mia"):
        w.subs[name], w.ids[name] = await member(maker, w.gremium_id, name)
    w.subs["Lea"], w.ids["Lea"] = await person(maker, "Lea")
    w.meeting_id = await meeting(maker, w.gremium_id, status="live")
    async with maker() as session:
        session.add(
            MeetingAttendance(meeting_id=w.meeting_id, principal_id=w.ids["Anna"], status="present")
        )
        session.add_all(
            MeetingDelegation(
                meeting_id=w.meeting_id,
                gremium_id=w.gremium_id,
                delegator_principal_id=w.ids[name],
                delegate_principal_id=w.ids["Lea"],
                delegate_voting=True,
                via_pool=pool,
                created_by="lead",
            )
            for name in ("Max", "Mia")
        )
        await session.commit()
    return w


def _row(rows: list[dict[str, object]], pid: uuid.UUID) -> dict[str, object]:
    return next(r for r in rows if r["principalId"] == str(pid))


async def test_the_roster_lists_a_delegate_who_is_no_member(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/delegations/003150: Lea has a row that names Max and Mia."""
    w = await _world(maker)
    act(api, None)
    with TestClient(api) as client:
        rows = client.get(f"/api/meetings/{w.meeting_id}/attendance").json()
    lea = _row(rows, w.ids["Lea"])
    assert lea["isMember"] is False
    assert lea["canVote"] is False
    assert lea["status"] is None
    assert [r["displayName"] for r in lea["represents"]] == ["Max", "Mia"]
    assert _row(rows, w.ids["Anna"])["isMember"] is True
    assert _row(rows, w.ids["Anna"])["represents"] == []


async def test_the_lead_and_the_delegate_set_the_attendance(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/delegations/003150: the lead sets Lea, then Lea reports herself."""
    w = await _world(maker)
    url = f"/api/meetings/{w.meeting_id}/attendance"
    with TestClient(api) as client:
        act(api, w.subs["Lea"])
        own = client.put(f"{url}/me", json={"status": "excused"})
        act(api, None)
        lead = client.put(f"{url}/{w.ids['Lea']}", json={"status": "present"})
    assert own.status_code == 200
    assert _row(own.json(), w.ids["Lea"])["status"] == "excused"
    assert lead.status_code == 200
    assert _row(lead.json(), w.ids["Lea"])["status"] == "present"
    assert _row(lead.json(), w.ids["Lea"])["source"] == "lead"


async def test_a_stranger_sets_no_attendance(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """A person who is neither a member nor a delegate gets 404 from the lead route."""
    w = await _world(maker)
    _, stranger = await person(maker, "Stan")
    act(api, None)
    with TestClient(api) as client:
        refused = client.put(
            f"/api/meetings/{w.meeting_id}/attendance/{stranger}", json={"status": "present"}
        )
    assert refused.status_code == 404


async def test_a_present_delegate_counts_in_the_one_count(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/delegations/003151: Anna and Lea give 2, Lea with two delegations once."""
    w = await _world(maker)
    async with maker() as session:
        assert await present_count(session, w.meeting_id) == Present(members=1, seats=0)
    act(api, None)
    with TestClient(api) as client:
        client.put(
            f"/api/meetings/{w.meeting_id}/attendance/{w.ids['Lea']}", json={"status": "present"}
        )
        head = client.get(f"/api/meetings/{w.meeting_id}").json()
    async with maker() as session:
        assert await present_count(session, w.meeting_id) == Present(members=1, seats=1)
    assert head["presentSeats"] == 1


async def test_a_pool_seat_without_a_record_reads_present(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/delegations/003152: a seat needs the live meeting, so Lea is present."""
    w = await _world(maker, pool=True)
    act(api, None)
    with TestClient(api) as client:
        rows = client.get(f"/api/meetings/{w.meeting_id}/attendance").json()
        client.put(
            f"/api/meetings/{w.meeting_id}/attendance/{w.ids['Lea']}", json={"status": "excused"}
        )
    assert _row(rows, w.ids["Lea"])["status"] == "present"
    async with maker() as session:
        assert await present_count(session, w.meeting_id) == Present(members=1, seats=0)


async def test_a_ballot_of_the_delegate_marks_the_delegate_present(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/delegations/003152: Lea casts for Max and Mia and is present."""
    w = await _world(maker)
    async with maker() as session:
        vote = Vote(
            application_id=None,
            meeting_id=w.meeting_id,
            eligible_group=str(w.gremium_id),
            config=MOTION,
            kind="motion",
            status="open",
        )
        session.add(vote)
        await session.commit()
        vote_id = vote.id
    act(api, w.subs["Lea"])
    with TestClient(api) as client:
        cast = client.post(
            f"/api/votes/{vote_id}/ballot", json={"choice": "yes", "asDelegation": True}
        )
    assert cast.status_code == 200, cast.text
    async with maker() as session:
        status = await session.scalar(
            select(MeetingAttendance.status).where(
                MeetingAttendance.meeting_id == w.meeting_id,
                MeetingAttendance.principal_id == w.ids["Lea"],
            )
        )
    assert status == "present"


async def test_the_protocol_names_the_delegate(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/protocols/003153: "Lea (für Max, Mia)" stands in the line Anwesend."""
    w = await _world(maker, pool=True)
    async with maker() as session:
        row = await session.get(Meeting, w.meeting_id)
        assert row is not None
        header = await ProtocolService(session)._header_meta(row)
        public = await ProtocolService(session)._header_meta(row, public=True)
    assert header.present == ["Anna", "Lea (für Max, Mia)"]
    assert header.present_count == 2
    assert public.present == []
    assert public.present_count == 2
