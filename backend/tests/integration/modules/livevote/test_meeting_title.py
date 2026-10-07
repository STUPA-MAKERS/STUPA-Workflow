"""The title of a meeting: editable while ``planned`` or ``live``, frozen after the close.

``PATCH /api/meetings/{id}`` takes ``title`` with the rule of the create: the server
strips the outer blanks and needs at least one character. A change writes
``meeting_update`` with the old and the new title. A closed meeting keeps its title
(409), because the protocol that goes out names the meeting.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.livevote.models import Meeting
from tests.integration.modules.livevote.conftest import audit_actions, seed

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("status", ["planned", "live"])
async def test_title_changes_while_not_closed(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, status: str
) -> None:
    s = await seed(maker, status=status)
    with TestClient(api) as client:
        res = client.patch(f"/api/meetings/{s.meeting_id}", json={"title": "  Vollversammlung "})
        assert res.status_code == 200, res.text
        assert res.json()["title"] == "Vollversammlung"
    async with maker() as session:
        meeting = await session.get(Meeting, s.meeting_id)
        assert meeting is not None
        assert meeting.title == "Vollversammlung"
    entries = await audit_actions(maker, target_id=s.meeting_id)
    assert [e.action for e in entries] == ["meeting_update"]
    assert entries[0].data["changes"] == {"title": {"from": "GV", "to": "Vollversammlung"}}


async def test_closed_meeting_keeps_its_title(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="closed")
    with TestClient(api) as client:
        res = client.patch(f"/api/meetings/{s.meeting_id}", json={"title": "Neu"})
        assert res.status_code == 409, res.text
        assert res.headers["content-type"].startswith("application/problem+json")
    async with maker() as session:
        meeting = await session.get(Meeting, s.meeting_id)
        assert meeting is not None
        assert meeting.title == "GV"
    assert await audit_actions(maker, target_id=s.meeting_id) == []


@pytest.mark.parametrize("title", ["", "   ", None, "x" * 201])
async def test_bad_title_is_refused(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, title: str | None
) -> None:
    s = await seed(maker, status="planned")
    with TestClient(api) as client:
        res = client.patch(f"/api/meetings/{s.meeting_id}", json={"title": title})
        assert res.status_code == 422, res.text
        assert res.headers["content-type"].startswith("application/problem+json")
