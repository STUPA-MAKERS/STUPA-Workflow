"""The open window of a meeting on a real Postgres.

* ``GET/PUT /admin/meeting-settings`` reads the seeded default (60 minutes), replaces
  it, refuses a body with a second value (422) and writes a ``config_change`` entry.
* ``GET/PUT /admin/gremium-defaults`` reads the defaults of a new Gremium and replaces
  them. A Gremium that exists keeps its values (§F/administration/admin/000906).
* ``PATCH /meetings/{id}`` with ``status: live`` gives 409 ``meeting_too_early``
  before the window. In the window the open needs nothing more
  (§F/meetings/meetings/000092). The planned meeting carries ``opensAt``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.meetings.models import Meeting
from tests.integration.modules.livevote.conftest import audit_actions, seed

pytestmark = pytest.mark.integration


async def _starts_in(maker: async_sessionmaker[AsyncSession], minutes: int) -> str:
    """Plan the meeting to start in `minutes` real minutes.

    The time is computed in UTC and then made local, so it is correct across a DST switch.
    """
    s = await seed(maker, status="planned")
    local = (datetime.now(UTC) + timedelta(minutes=minutes)).astimezone(ZoneInfo("Europe/Berlin"))
    async with maker() as session:
        meeting = await session.get(Meeting, s.meeting_id)
        assert meeting is not None
        meeting.date = local.date()
        meeting.start_time = local.time().replace(second=0, microsecond=0)
        await session.commit()
    return f"/api/meetings/{s.meeting_id}"


async def test_settings_defaults_update_and_audit(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    with TestClient(api) as client:
        got = client.get("/api/admin/meeting-settings")
        assert got.status_code == 200, got.text
        assert got.json()["openLeadMinutes"] == 60
        assert "confirmLeadMinutes" not in got.json()
        bad = client.put(
            "/api/admin/meeting-settings",
            json={"openLeadMinutes": 120, "confirmLeadMinutes": 30},
        )
        assert bad.status_code == 422, bad.text
        put = client.put("/api/admin/meeting-settings", json={"openLeadMinutes": 120})
        assert put.status_code == 200, put.text
        assert put.json()["openLeadMinutes"] == 120
    [entry] = [e for e in await audit_actions(maker) if e.target_type == "meeting_settings"]
    assert entry.data == {"openLeadMinutes": {"from": 60, "to": 120}}


async def test_gremium_defaults_leave_an_old_gremium(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """Change a default and read an old Gremium.

    §F/administration/admin/000906: the defaults start with 40, 25, off, off, 120 and 2. A
    change of a default changes no Gremium that exists.
    """
    with TestClient(api) as client:
        got = client.get("/api/admin/gremium-defaults")
        assert got.status_code == 200, got.text
        assert got.json() == {
            "quorumPercent": 40,
            "repeatQuorumPercent": 25,
            "guestsMayVote": False,
            "allowVoteDelegation": False,
            "delegationLeadMinutes": 120,
            "delegationMaxPerDelegate": 2,
        }
        tag = uuid.uuid4().hex[:8]
        old = client.post(
            "/api/admin/committees",
            json={
                "name": f"Alt {tag}",
                "slug": f"alt-{tag}",
                "quorumPercent": 40,
                "repeatQuorumPercent": 25,
            },
        )
        assert old.status_code in (200, 201), old.text
        changed = {
            "quorumPercent": 50,
            "repeatQuorumPercent": 30,
            "guestsMayVote": True,
            "allowVoteDelegation": True,
            "delegationLeadMinutes": 60,
            "delegationMaxPerDelegate": 2,
        }
        put = client.put("/api/admin/gremium-defaults", json=changed)
        assert put.status_code == 200, put.text
        assert put.json() == changed
        assert client.get("/api/admin/gremium-defaults").json() == changed
        bad = client.put("/api/admin/gremium-defaults", json={**changed, "quorumPercent": 101})
        assert bad.status_code == 422, bad.text
        rows = client.get("/api/admin/committees").json()
        [row] = [g for g in rows if g["id"] == old.json()["id"]]
        assert (row["quorumPercent"], row["repeatQuorumPercent"]) == (40, 25)
        assert row["guestsMayVote"] is False and row["allowVoteDelegation"] is False
        settings = client.get("/api/admin/meeting-settings").json()
        assert settings["openLeadMinutes"] == 60
    entries = [e for e in await audit_actions(maker) if e.target_type == "meeting_settings"]
    assert entries[-1].data["gremiumDefaults"]["quorumPercent"] == {"from": 40, "to": 50}


async def test_open_before_the_window_conflicts(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    url = await _starts_in(maker, 180)
    with TestClient(api) as client:
        meeting = client.get(url).json()
        assert meeting["opensAt"] is not None
        assert "confirmUntil" not in meeting
        early = client.patch(url, json={"status": "live"})
        assert early.status_code == 409, early.text
        assert early.json()["code"] == "meeting_too_early"


async def test_open_in_the_window_needs_no_confirmation(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/meetings/000092: in the window the open needs nothing more."""
    url = await _starts_in(maker, 30)
    with TestClient(api) as client:
        started = client.patch(url, json={"status": "live"})
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "live"
        assert started.json()["opensAt"] is None
