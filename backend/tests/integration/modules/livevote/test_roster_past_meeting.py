"""The roster of a meeting does not depend on the memberships that are valid now.

A closed meeting keeps the people who attended it. The roster holds the members
whose membership overlaps the meeting window, plus each principal with an
attendance record for the meeting. A member whose membership started after the
meeting, or ended before it, is not on the roster. The protocol quorum counts the
same roster.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.livevote.models import Meeting, MeetingAttendance
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
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
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
                    principal_id=row.id,
                    gremium_id=gremium_id,
                    gremium_role_id=role.id,
                    valid_from=valid_from,
                    valid_until=valid_until,
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
    """Seed a closed meeting with one principal per roster case."""
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
        # The membership ended after the meeting: on the roster with the record.
        "ended_later": await _principal(
            maker,
            g,
            "Anna",
            valid_until=datetime(2026, 7, 1, tzinfo=UTC),
            status="present",
            meeting_id=m,
        ),
        # A record without any membership (for example removed by the OIDC sync).
        "record_only": await _principal(
            maker, g, "Bert", member=False, status="present", meeting_id=m
        ),
        # An open membership without a record: on the roster, status open.
        "open_member": await _principal(maker, g, "Carla"),
        # The membership started after the meeting: not on the roster.
        "joined_later": await _principal(
            maker, g, "Dora", valid_from=datetime(2026, 8, 1, tzinfo=UTC)
        ),
        # The membership ended before the meeting: not on the roster.
        "left_before": await _principal(
            maker, g, "Emil", valid_until=datetime(2026, 6, 1, tzinfo=UTC)
        ),
        # The membership ended during the meeting, excused: on the roster.
        "ended_during": await _principal(
            maker,
            g,
            "Fritz",
            valid_until=datetime(2026, 6, 20, 17, 0, tzinfo=UTC),
            status="excused",
            meeting_id=m,
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
    want = {"ended_later", "record_only", "open_member", "ended_during"}
    assert set(roster) == {str(ids[k]) for k in want}
    assert roster[str(ids["ended_later"])]["status"] == "present"
    assert roster[str(ids["record_only"])]["status"] == "present"
    assert roster[str(ids["ended_during"])]["status"] == "excused"
    assert roster[str(ids["open_member"])]["status"] is None
    statuses = [r["status"] for r in roster.values()]
    assert statuses.count("present") == 2
    assert statuses.count("excused") == 1


async def test_live_meeting_roster_holds_current_members_and_records(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """A live meeting: the current members, plus a recorded principal without one."""
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
    future = await _principal(
        maker, s.gremium_id, "Carla", valid_from=datetime(2099, 1, 1, tzinfo=UTC)
    )
    with TestClient(api) as client:
        resp = client.get(f"/api/meetings/{s.meeting_id}/attendance")
    assert resp.status_code == 200, resp.text
    got = {r["principalId"] for r in resp.json()}
    assert str(current) in got
    assert str(recorded) in got
    assert str(future) not in got


async def test_protocol_quorum_counts_the_meeting_roster(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The quorum of a closed meeting counts its roster, not the members of now.

    The roster has 4 entries and 2 are present, so a 50 % quorum holds. The members
    that are valid now are 2 (Carla and Dora), which would give the wrong count.
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
        # Without a meeting the members that are valid now count (Carla, Dora).
        assert await svc._quorate(gremium, None, 1) is True
