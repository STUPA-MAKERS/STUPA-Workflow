"""Z2, O15, O23, A7 and F12: the attendance rules through the real API.

* A member reports the own attendance as present or excused only (422 for absent).
* The record of the meeting lead wins: the member gets 409 until the lead resets it.
* The lead cannot set a member present while a delegation of that member exists.
* The reason of an excuse goes only to the member and to the lead.
* The lead's set and reset are audited, never with the reason. The own report is not.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deps import get_current_principal
from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import MeetingDelegation
from app.modules.livevote.models import MeetingAttendance
from tests.integration.modules.livevote.conftest import ADMIN_SUB, admin, audit_actions, seed

pytestmark = pytest.mark.integration


async def _member(
    maker: async_sessionmaker[AsyncSession], gremium_id: uuid.UUID, name: str
) -> tuple[str, uuid.UUID]:
    """Write a plain member of the gremium (no lead rights) and return sub and id."""
    sub = f"{name}-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        row = PrincipalRow(sub=sub, display_name=name, email=f"{sub}@x.de")
        role = GremiumRole(
            gremium_id=gremium_id,
            key=f"m-{sub}",
            name_i18n={"de": "Mitglied"},
            permissions=["vote.cast"],
        )
        session.add_all([row, role])
        await session.flush()
        session.add(
            GremiumMembership(principal_id=row.id, gremium_id=gremium_id, gremium_role_id=role.id)
        )
        await session.commit()
    return sub, row.id


def _as(api: FastAPI, sub: str | None) -> None:
    """Act as the member `sub`, or as the admin lead for `None`."""
    api.dependency_overrides[get_current_principal] = (
        admin if sub is None else (lambda: Principal(sub=sub))
    )


def _row(roster: list[dict[str, object]], principal_id: uuid.UUID) -> dict[str, object]:
    return next(r for r in roster if r["principalId"] == str(principal_id))


@pytest.mark.parametrize("status", ["planned", "live"])
async def test_member_reports_present_or_excused_only(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, status: str
) -> None:
    s = await seed(maker, status=status, items=0)
    sub, pid = await _member(maker, s.gremium_id, "Anna")
    _as(api, sub)
    url = f"/api/meetings/{s.meeting_id}/attendance/me"
    with TestClient(api) as client:
        absent = client.put(url, json={"status": "absent"})
        note_on_present = client.put(url, json={"status": "present", "note": "x"})
        excused = client.put(url, json={"status": "excused", "note": "Krank"})
    assert absent.status_code == 422, absent.text
    assert absent.headers["content-type"].startswith("application/problem+json")
    assert note_on_present.status_code == 422, note_on_present.text
    assert excused.status_code == 200, excused.text
    me = _row(excused.json(), pid)
    assert (me["status"], me["source"], me["note"], me["isSelf"]) == (
        "excused",
        "self",
        "Krank",
        True,
    )
    # The own report is not audited.
    assert await audit_actions(maker, target_id=s.meeting_id) == []


async def test_lead_status_wins_until_reset(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", items=0)
    sub, pid = await _member(maker, s.gremium_id, "Anna")
    me = f"/api/meetings/{s.meeting_id}/attendance/me"
    lead = f"/api/meetings/{s.meeting_id}/attendance/{pid}"
    with TestClient(api) as client:
        _as(api, sub)
        assert client.put(me, json={"status": "present"}).status_code == 200
        _as(api, None)
        set_resp = client.put(lead, json={"status": "absent"})
        assert set_resp.status_code == 200, set_resp.text
        assert _row(set_resp.json(), pid)["source"] == "lead"
        _as(api, sub)
        refused = client.put(me, json={"status": "present"})
        _as(api, None)
        reset = client.delete(lead)
        _as(api, sub)
        again = client.put(me, json={"status": "present"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "attendance_set_by_lead"
    assert reset.status_code == 200, reset.text
    assert _row(reset.json(), pid)["status"] is None
    assert _row(reset.json(), pid)["source"] is None
    assert again.status_code == 200, again.text
    assert _row(again.json(), pid)["source"] == "self"


async def test_member_cannot_set_or_reset_others(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", items=0)
    sub, _ = await _member(maker, s.gremium_id, "Anna")
    _, other = await _member(maker, s.gremium_id, "Bert")
    _as(api, sub)
    url = f"/api/meetings/{s.meeting_id}/attendance/{other}"
    with TestClient(api) as client:
        put = client.put(url, json={"status": "absent"})
        delete = client.delete(url)
    assert put.status_code == 403, put.text
    assert delete.status_code == 403, delete.text


async def test_present_refused_while_delegation_is_active(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """O23: the lead first revokes the delegation, then sets the member present."""
    s = await seed(maker, status="live", items=0)
    _, delegator = await _member(maker, s.gremium_id, "Anna")
    _, delegate = await _member(maker, s.gremium_id, "Bert")
    async with maker() as session:
        session.add(
            MeetingDelegation(
                meeting_id=s.meeting_id,
                gremium_id=s.gremium_id,
                delegator_principal_id=delegator,
                delegate_principal_id=delegate,
                delegate_voting=True,
            )
        )
        await session.commit()
    url = f"/api/meetings/{s.meeting_id}/attendance/{delegator}"
    with TestClient(api) as client:
        present = client.put(url, json={"status": "present"})
        excused = client.put(url, json={"status": "excused"})
        delegate_present = client.put(
            f"/api/meetings/{s.meeting_id}/attendance/{delegate}", json={"status": "present"}
        )
    assert present.status_code == 409, present.text
    assert present.json()["code"] == "delegation_active"
    assert excused.status_code == 200, excused.text
    # Only the delegator is blocked, not the delegate.
    assert delegate_present.status_code == 200, delegate_present.text


async def test_note_only_for_the_member_and_the_lead(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="planned", items=0)
    anna, anna_id = await _member(maker, s.gremium_id, "Anna")
    bert, _ = await _member(maker, s.gremium_id, "Bert")
    url = f"/api/meetings/{s.meeting_id}/attendance"
    with TestClient(api) as client:
        _as(api, anna)
        own_put = client.put(f"{url}/me", json={"status": "excused", "note": "Krank"})
        assert own_put.status_code == 200, own_put.text
        own = client.get(url).json()
        _as(api, bert)
        other = client.get(url).json()
        _as(api, None)
        lead = client.get(url).json()
    assert _row(own, anna_id)["note"] == "Krank"
    assert _row(other, anna_id)["note"] is None
    assert _row(other, anna_id)["status"] == "excused"
    assert _row(lead, anna_id)["note"] == "Krank"


async def test_lead_changes_are_audited_without_the_note(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", items=0)
    _, pid = await _member(maker, s.gremium_id, "Anna")
    url = f"/api/meetings/{s.meeting_id}/attendance/{pid}"
    with TestClient(api) as client:
        first = client.put(url, json={"status": "excused", "note": "Zahnarzt"})
        assert first.status_code == 200, first.text
        assert _row(first.json(), pid)["note"] == "Zahnarzt"
        # Without a note the excuse keeps its reason.
        kept = client.put(url, json={"status": "excused"})
        assert _row(kept.json(), pid)["note"] == "Zahnarzt"
        assert client.put(url, json={"status": "absent"}).status_code == 200
        assert client.delete(url).status_code == 200
        # A second reset finds no record: no change and no audit entry.
        assert client.delete(url).status_code == 200
    entries = await audit_actions(maker, target_id=s.meeting_id)
    assert [e.action for e in entries] == [
        "attendance_set",
        "attendance_set",
        "attendance_set",
        "attendance_reset",
    ]
    assert all(e.actor == ADMIN_SUB for e in entries)
    assert entries[0].data == {
        "principalId": str(pid),
        "status": {"from": None, "to": "excused"},
        "source": {"from": None, "to": "lead"},
    }
    assert entries[2].data["status"] == {"from": "excused", "to": "absent"}
    assert entries[3].data["status"] == {"from": "absent", "to": None}
    assert "Zahnarzt" not in str([e.data for e in entries])
    async with maker() as session:
        rows = (
            await session.scalars(
                select(MeetingAttendance).where(MeetingAttendance.meeting_id == s.meeting_id)
            )
        ).all()
    assert rows == []


async def test_closed_meeting_freezes_the_attendance(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="closed", items=0)
    sub, pid = await _member(maker, s.gremium_id, "Anna")
    url = f"/api/meetings/{s.meeting_id}/attendance"
    with TestClient(api) as client:
        lead_set = client.put(f"{url}/{pid}", json={"status": "absent"})
        lead_reset = client.delete(f"{url}/{pid}")
        _as(api, sub)
        own = client.put(f"{url}/me", json={"status": "present"})
    for resp in (lead_set, lead_reset, own):
        assert resp.status_code == 409, resp.text
    assert await audit_actions(maker, target_id=s.meeting_id) == []


async def test_database_refuses_a_new_self_absent_row(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The NOT VALID check still covers every new row."""
    s = await seed(maker, status="live", items=0)
    _, pid = await _member(maker, s.gremium_id, "Anna")
    async with maker() as session:
        session.add(
            MeetingAttendance(
                meeting_id=s.meeting_id, principal_id=pid, status="absent", source="self"
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
