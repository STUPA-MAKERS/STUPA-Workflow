"""The open window of a meeting on a real Postgres.

* ``GET/PUT /admin/meeting-settings`` reads the seeded defaults (60 and 10 minutes),
  replaces them, refuses a confirmation point before the earliest open (422) and
  writes a ``config_change`` entry.
* ``PATCH /meetings/{id}`` with ``status: live`` gives 409 ``meeting_too_early``
  before the window and 409 ``early_open_unconfirmed`` in the early part without
  ``confirmEarly``. The planned meeting carries ``opensAt`` and ``confirmUntil``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.livevote.models import Meeting
from tests.integration.modules.livevote.conftest import audit_actions, seed

pytestmark = pytest.mark.integration


async def _starts_in(
    maker: async_sessionmaker[AsyncSession], minutes: int
) -> str:
    s = await seed(maker, status="planned")
    local = datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(minutes=minutes)
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
        assert got.json()["confirmLeadMinutes"] == 10
        bad = client.put(
            "/api/admin/meeting-settings",
            json={"openLeadMinutes": 10, "confirmLeadMinutes": 20},
        )
        assert bad.status_code == 422, bad.text
        put = client.put(
            "/api/admin/meeting-settings",
            json={"openLeadMinutes": 120, "confirmLeadMinutes": 30},
        )
        assert put.status_code == 200, put.text
        assert put.json()["openLeadMinutes"] == 120
        assert put.json()["confirmLeadMinutes"] == 30
    [entry] = [e for e in await audit_actions(maker) if e.target_type == "meeting_settings"]
    assert entry.data == {
        "openLeadMinutes": {"from": 60, "to": 120},
        "confirmLeadMinutes": {"from": 10, "to": 30},
    }


async def test_open_before_the_window_conflicts(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    url = await _starts_in(maker, 180)
    with TestClient(api) as client:
        meeting = client.get(url).json()
        assert meeting["opensAt"] is not None
        assert meeting["confirmUntil"] is not None
        early = client.patch(url, json={"status": "live", "confirmEarly": True})
        assert early.status_code == 409, early.text
        assert early.json()["code"] == "meeting_too_early"


async def test_early_open_needs_the_confirmation(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    url = await _starts_in(maker, 30)
    with TestClient(api) as client:
        refused = client.patch(url, json={"status": "live"})
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "early_open_unconfirmed"
        started = client.patch(url, json={"status": "live", "confirmEarly": True})
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "live"
        assert started.json()["opensAt"] is None
