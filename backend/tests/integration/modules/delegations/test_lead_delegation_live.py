"""O6: the meeting lead enters a substitution for a missing member while live.

* Only the lead (`session.manage` in the gremium) may send `delegatorId`, and
  only while the meeting is live.
* The member is missing: no attendance record, `excused` or `absent`.
* The delegate is a substitute of the faculty group of the member. A personal
  pool entry is not enough.
* The existing checks still apply: the vote right of the member and no second
  delegation.
* The row stores the lead as `created_by` and `via_pool = true`.
* The lead revokes while live. A ballot that the delegate already cast stays.
* The lead cannot name themselves as the substitute.
* The entry waits for a parallel attendance change of the member (O23).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import DelegationSubstitute, MeetingDelegation
from app.modules.delegations.schemas import DelegationCreate
from app.modules.delegations.service import DelegationService
from app.modules.livevote.models import Meeting, MeetingAttendance
from app.modules.voting.models import Ballot, Vote
from app.settings import load_settings
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ValidationProblem
from tests.integration.modules.delegations.conftest import (
    act,
    faculty_group,
    gremium,
    meeting,
    member,
    person,
)

pytestmark = pytest.mark.integration

CONFIG = VoteConfig.model_validate(
    {"options": ["yes", "no", "abstain"], "majorityRule": "simple"}
).model_dump(by_alias=True)


class _Setup:
    """Ids of one live meeting with a lead, a member A and a group substitute B."""

    def __init__(self) -> None:
        self.gremium_id = uuid.uuid4()
        self.meeting_id = uuid.uuid4()
        self.lead = ""
        self.a_sub = ""
        self.a = uuid.uuid4()
        self.b_sub = ""
        self.b = uuid.uuid4()


async def _setup(maker: async_sessionmaker[AsyncSession], *, status: str = "live") -> _Setup:
    s = _Setup()
    s.gremium_id = await gremium(maker)
    s.lead, _ = await member(maker, s.gremium_id, "Lead", ("session.manage", "vote.cast"))
    s.a_sub, s.a = await member(maker, s.gremium_id, "Anna")
    s.b_sub, s.b = await person(maker, "Bert")
    await faculty_group(maker, s.gremium_id, members=(s.a,), substitutes=(s.b,))
    s.meeting_id = await meeting(maker, s.gremium_id, status=status)
    return s


async def _principal_id(maker: async_sessionmaker[AsyncSession], sub: str) -> uuid.UUID:
    async with maker() as session:
        pid = await session.scalar(select(PrincipalRow.id).where(PrincipalRow.sub == sub))
    assert pid is not None
    return pid


def _body(s: _Setup, *, voting: bool = True, delegate: uuid.UUID | None = None) -> dict:
    return {
        "meetingId": str(s.meeting_id),
        "delegatorId": str(s.a),
        "delegateId": str(delegate or s.b),
        "delegateVoting": voting,
    }


async def _attendance(
    maker: async_sessionmaker[AsyncSession], s: _Setup, status: str, source: str = "lead"
) -> None:
    async with maker() as session:
        session.add(
            MeetingAttendance(
                meeting_id=s.meeting_id, principal_id=s.a, status=status, source=source
            )
        )
        await session.commit()


@pytest.mark.parametrize("status", [None, "absent", "excused"])
async def test_lead_enters_a_substitution_for_a_missing_member(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, status: str | None
) -> None:
    s = await _setup(maker)
    if status is not None:
        await _attendance(maker, s, status)
    act(api, s.lead)
    with TestClient(api) as client:
        created = client.post("/api/delegations", json=_body(s))
        listed = client.get("/api/delegations", params={"meetingId": str(s.meeting_id)})
    assert created.status_code == 201, created.text
    out = created.json()
    assert (out["delegatorId"], out["delegateId"]) == (str(s.a), str(s.b))
    assert (out["viaPool"], out["delegateVoting"], out["revocable"]) == (True, True, True)
    assert [d["id"] for d in listed.json()] == [out["id"]]
    assert listed.json()[0]["revocable"] is True
    async with maker() as session:
        row = await session.get(MeetingDelegation, uuid.UUID(out["id"]))
        assert row is not None
        assert (row.created_by, row.via_pool) == (s.lead, True)
        entry = (
            await session.scalars(
                select(AuditEntry).where(AuditEntry.target_id == out["id"])
            )
        ).one()
    assert entry.action == "delegation_grant"
    assert entry.actor == s.lead
    assert entry.data["byLead"] is True
    assert entry.data["delegatorId"] == str(s.a)


async def test_lead_revokes_and_the_cast_ballot_stays(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await _setup(maker)
    async with maker() as session:
        vote = Vote(
            application_id=None,
            meeting_id=s.meeting_id,
            eligible_group=str(s.gremium_id),
            config=CONFIG,
            status="open",
        )
        session.add(vote)
        await session.commit()
        vote_id = vote.id
    with TestClient(api) as client:
        act(api, s.lead)
        created = client.post("/api/delegations", json=_body(s))
        assert created.status_code == 201, created.text
        act(api, s.b_sub)
        cast = client.post(
            f"/api/votes/{vote_id}/ballot", json={"choice": "yes", "asDelegation": True}
        )
        # The delegator cannot revoke after the start.
        act(api, s.a_sub)
        own = client.delete(f"/api/delegations/{created.json()['id']}")
        act(api, s.lead)
        revoked = client.delete(f"/api/delegations/{created.json()['id']}")
    assert cast.status_code == 200, cast.text
    assert own.status_code == 422, own.text
    assert revoked.status_code == 204, revoked.text
    async with maker() as session:
        ballots = (
            await session.scalars(select(Ballot.voter_sub).where(Ballot.vote_id == vote_id))
        ).all()
        assert ballots == [s.a_sub]
        assert await session.get(MeetingDelegation, uuid.UUID(created.json()["id"])) is None
        entry = (
            await session.scalars(
                select(AuditEntry).where(
                    AuditEntry.action == "delegation_revoke",
                    AuditEntry.target_id == created.json()["id"],
                )
            )
        ).one()
    assert entry.data["byLead"] is True


async def test_only_the_lead_and_only_while_live(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await _setup(maker, status="planned")
    other_lead, _ = await member(maker, await gremium(maker), "Other", ("session.manage",))
    with TestClient(api) as client:
        act(api, s.lead)
        planned = client.post("/api/delegations", json=_body(s))
        act(api, s.a_sub)
        by_member = client.post("/api/delegations", json=_body(s))
        act(api, other_lead)
        by_foreign_lead = client.post("/api/delegations", json=_body(s))
        act(api, s.lead, scope=frozenset({"meeting.view_all"}))
        scoped = client.post("/api/delegations", json=_body(s))
    assert planned.status_code == 422, planned.text
    assert by_member.status_code == 403, by_member.text
    assert by_foreign_lead.status_code == 403, by_foreign_lead.text
    assert scoped.status_code == 403, scoped.text


async def test_the_checks_of_the_lead_entry(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await _setup(maker)
    _, personal = await person(maker, "Pool")
    _, voteless = await member(maker, s.gremium_id, "Guest", ())
    async with maker() as session:
        session.add(
            DelegationSubstitute(
                gremium_id=s.gremium_id, member_principal_id=s.a, substitute_principal_id=personal
            )
        )
        await session.commit()
    act(api, s.lead)
    with TestClient(api) as client:
        not_in_group = client.post("/api/delegations", json=_body(s, delegate=personal))
        same = client.post("/api/delegations", json=_body(s, delegate=s.a))
        unknown = client.post("/api/delegations", json=_body(s, delegate=uuid.uuid4()))
        no_vote = client.post(
            "/api/delegations",
            json={**_body(s), "delegatorId": str(voteless)},
        )
        first = client.post("/api/delegations", json=_body(s))
        second = client.post("/api/delegations", json=_body(s, voting=False))
    assert not_in_group.status_code == 403, not_in_group.text
    assert same.status_code == 422, same.text
    assert unknown.status_code == 404, unknown.text
    assert no_vote.status_code == 403, no_vote.text
    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text


async def test_a_present_member_needs_no_substitution(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await _setup(maker)
    await _attendance(maker, s, "present", source="self")
    act(api, s.lead)
    with TestClient(api) as client:
        refused = client.post("/api/delegations", json=_body(s))
    assert refused.status_code == 422, refused.text
    assert refused.headers["content-type"].startswith("application/problem+json")


async def test_lead_cannot_revoke_a_planned_delegation_of_another_member(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await _setup(maker, status="planned")
    with TestClient(api) as client:
        act(api, s.a_sub)
        own = client.post(
            "/api/delegations",
            json={"meetingId": str(s.meeting_id), "delegateId": str(s.b)},
        )
        assert own.status_code == 201, own.text
        act(api, s.lead)
        listed = client.get("/api/delegations", params={"meetingId": str(s.meeting_id)})
        refused = client.delete(f"/api/delegations/{own.json()['id']}")
    assert refused.status_code == 403, refused.text
    # The flag agrees with the refusal: the lead sees the row but cannot revoke it.
    assert [(d["id"], d["revocable"]) for d in listed.json()] == [(own.json()["id"], False)]


async def test_lead_cannot_name_themselves(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await _setup(maker)
    lead_id = await _principal_id(maker, s.lead)
    # The lead is also a substitute of the group of A. Still the lead cannot take
    # the vote of A without the consent of A.
    await faculty_group(maker, s.gremium_id, substitutes=(lead_id,), name="Technik")
    act(api, s.lead)
    with TestClient(api) as client:
        refused = client.post("/api/delegations", json=_body(s, delegate=lead_id))
    assert refused.status_code == 403, refused.text
    async with maker() as session:
        rows = (
            await session.scalars(
                select(MeetingDelegation).where(MeetingDelegation.meeting_id == s.meeting_id)
            )
        ).all()
    assert rows == []


async def test_lead_entry_waits_for_a_parallel_present_report(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """A holds the share lock of the attendance writer and reports present (O23).

    The lead entry for A must wait for the lock. After the commit it reads the
    present record and refuses. Without the wait both changes would commit.
    """
    s = await _setup(maker)
    service_settings = load_settings(delegation_voting_enabled=True)
    payload = DelegationCreate.model_validate(_body(s))
    async with maker() as writer, maker() as lead_session:
        await writer.execute(
            select(Meeting.id).where(Meeting.id == s.meeting_id).with_for_update(read=True)
        )
        writer.add(
            MeetingAttendance(
                meeting_id=s.meeting_id, principal_id=s.a, status="present", source="self"
            )
        )
        await writer.flush()
        entry = asyncio.create_task(
            DelegationService(lead_session, service_settings).create(
                payload, Principal(sub=s.lead)
            )
        )
        await asyncio.sleep(0.5)
        assert not entry.done()
        await writer.commit()
        with pytest.raises(ValidationProblem, match="present"):
            await asyncio.wait_for(entry, timeout=10)
    async with maker() as session:
        rows = (
            await session.scalars(
                select(MeetingDelegation).where(MeetingDelegation.meeting_id == s.meeting_id)
            )
        ).all()
    assert rows == []
