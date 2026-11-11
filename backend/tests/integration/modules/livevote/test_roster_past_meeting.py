"""The roster of a meeting holds the members and each recorded principal.

A closed meeting keeps the people who attended it. The roster holds the members of
the Gremium, plus each principal with an attendance record for the meeting, also
after the OIDC sync removed the membership. A principal without a membership and
without a record is not on the roster. The protocol quorum counts the same roster.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.gremien.models import Gremium, GremiumMembership, GremiumRole
from app.modules.meetings.models import Meeting, MeetingAttendance
from app.modules.protocol.service import ProtocolService
from tests.integration.modules.livevote.conftest import seed

pytestmark = pytest.mark.integration

STARTED = datetime(2026, 6, 20, 16, 0, tzinfo=UTC)
CLOSED = datetime(2026, 6, 20, 18, 0, tzinfo=UTC)


async def _principal(
    maker: async_sessionmaker[AsyncSession],
    gremium_id: uuid.UUID,
    name: str,
    *,
    member: bool = True,
    status: str | None = None,
    meeting_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Write a principal, an optional membership and an optional attendance record."""
    sub = f"{name}-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        row = PrincipalRow(sub=sub, display_name=name, email=f"{sub}@x.de")
        session.add(row)
        await session.flush()
        if member:
            role = GremiumRole(
                gremium_id=gremium_id,
                key=f"m-{sub}",
                name_i18n={"de": "Mitglied"},
                permissions=["vote.cast"],
            )
            session.add(role)
            await session.flush()
            session.add(
                GremiumMembership(
                    principal_id=row.id, gremium_id=gremium_id, gremium_role_id=role.id
                )
            )
        if status is not None and meeting_id is not None:
            session.add(
                MeetingAttendance(
                    meeting_id=meeting_id, principal_id=row.id, status=status, source="self"
                )
            )
        await session.commit()
    return row.id


async def _closed_meeting(
    maker: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID, dict[str, uuid.UUID]]:
    """Seed a closed meeting with one principal per roster case.

    The cases: a member with a record is on the roster with the record. A record
    without any membership, for example after the OIDC sync removed it, is on the
    roster. A member without a record is on the roster with an open status. A
    principal without a membership and without a record is not on the roster.
    """
    s = await seed(maker, status="closed", items=0)
    async with maker() as session:
        await session.execute(
            update(Meeting)
            .where(Meeting.id == s.meeting_id)
            .values(started_at=STARTED, closed_at=CLOSED)
        )
        await session.commit()
    g, m = s.gremium_id, s.meeting_id
    ids = {
        "member_present": await _principal(
            maker, g, "Anna", status="present", meeting_id=m
        ),
        "record_only": await _principal(
            maker, g, "Bert", member=False, status="present", meeting_id=m
        ),
        "open_member": await _principal(maker, g, "Carla"),
        "outsider": await _principal(maker, g, "Emil", member=False),
        "member_excused": await _principal(
            maker, g, "Fritz", status="excused", meeting_id=m
        ),
    }
    return g, m, ids


async def test_closed_meeting_roster_keeps_recorded_attendance(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    _, meeting_id, ids = await _closed_meeting(maker)
    with TestClient(api) as client:
        resp = client.get(f"/api/meetings/{meeting_id}/attendance")
    assert resp.status_code == 200, resp.text
    roster = {r["principalId"]: r for r in resp.json()}
    want = {"member_present", "record_only", "open_member", "member_excused"}
    assert set(roster) == {str(ids[k]) for k in want}
    assert roster[str(ids["member_present"])]["status"] == "present"
    assert roster[str(ids["record_only"])]["status"] == "present"
    assert roster[str(ids["member_excused"])]["status"] == "excused"
    assert roster[str(ids["open_member"])]["status"] is None
    statuses = [r["status"] for r in roster.values()]
    assert statuses.count("present") == 2
    assert statuses.count("excused") == 1


async def test_live_meeting_roster_holds_current_members_and_records(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """A live meeting: the members, plus a recorded principal without a membership."""
    s = await seed(maker, status="live", items=0)
    async with maker() as session:
        await session.execute(
            update(Meeting).where(Meeting.id == s.meeting_id).values(started_at=STARTED)
        )
        await session.commit()
    current = await _principal(maker, s.gremium_id, "Anna")
    recorded = await _principal(
        maker, s.gremium_id, "Bert", member=False, status="present", meeting_id=s.meeting_id
    )
    outsider = await _principal(maker, s.gremium_id, "Carla", member=False)
    with TestClient(api) as client:
        resp = client.get(f"/api/meetings/{s.meeting_id}/attendance")
    assert resp.status_code == 200, resp.text
    got = {r["principalId"] for r in resp.json()}
    assert str(current) in got
    assert str(recorded) in got
    assert str(outsider) not in got


async def test_protocol_quorum_counts_the_meeting_roster(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The quorum of a closed meeting counts its roster, not only the members.

    The roster has 4 entries and 2 are present, so a 50 % quorum holds and 1
    present does not. Without a meeting the 3 members count (Anna, Carla, Fritz).
    """
    gremium_id, meeting_id, _ = await _closed_meeting(maker)
    async with maker() as session:
        gremium = await session.get(Gremium, gremium_id)
        meeting = await session.get(Meeting, meeting_id)
        assert gremium is not None and meeting is not None
        gremium.quorum_percent = 50
        svc = ProtocolService(session)
        assert await svc._quorate(gremium, meeting, 2) is True
        assert await svc._quorate(gremium, meeting, 1) is False
        assert await svc._quorate(gremium, None, 2) is True
        assert await svc._quorate(gremium, None, 1) is False
