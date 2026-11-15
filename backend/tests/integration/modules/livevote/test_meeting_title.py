"""The title of a meeting: editable until the protocol of the closed meeting is final.

``PATCH /api/meetings/{id}`` takes ``title`` with the rule of the create: the server
strips the outer blanks and needs at least one character. A change writes
``meeting_update`` with the old and the new title. A closed meeting takes a correction of
its head data until its protocol is final (§F/meetings/meetings/000982).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.meetings.models import Meeting
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


async def test_closed_meeting_takes_corrections_until_the_protocol_is_final(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§F/meetings/meetings/000982: head data and item title stay open, the list is closed."""
    s = await seed(maker, status="closed", items=2, protocol="draft")
    agenda = f"/api/meetings/{s.meeting_id}/agenda"
    with TestClient(api) as client:
        res = client.patch(
            f"/api/meetings/{s.meeting_id}", json={"title": "Neu", "location": "Raum 9-042"}
        )
        assert res.status_code == 200, res.text
        assert (res.json()["title"], res.json()["location"]) == ("Neu", "Raum 9-042")
        item = client.patch(
            f"{agenda}/{s.item_ids[0]}", json={"title": "Umbenannt", "nonPublic": True}
        )
        assert item.status_code == 200, item.text
        assert (item.json()[0]["title"], item.json()[0]["nonPublic"]) == ("Umbenannt", True)
        closed = [
            client.post(agenda, json={"title": "Neu"}),
            client.put(f"{agenda}/order", json={"itemIds": [str(i) for i in s.item_ids[::-1]]}),
            client.delete(f"{agenda}/{s.item_ids[1]}"),
            client.patch(f"/api/meetings/{s.meeting_id}", json={"kind": "extraordinary"}),
        ]
    assert [(r.status_code, r.json()["code"]) for r in closed] == [(409, "meeting_closed")] * 4
    entries = await audit_actions(maker, target_id=s.meeting_id)
    assert [e.action for e in entries] == ["meeting_update", "agenda_item_update"]


@pytest.mark.parametrize("protocol", ["rendering", "final"])
async def test_final_protocol_closes_the_corrections(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, protocol: str
) -> None:
    """§F/meetings/meetings/000982: after the finalization each change answers 409."""
    s = await seed(maker, status="closed", protocol=protocol)
    with TestClient(api) as client:
        refused = [
            client.patch(f"/api/meetings/{s.meeting_id}", json={"title": "Neu"}),
            client.patch(
                f"/api/meetings/{s.meeting_id}/agenda/{s.item_ids[0]}", json={"title": "Neu"}
            ),
        ]
    for res in refused:
        assert (res.status_code, res.json()["code"]) == (409, "protocol_final"), res.text
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
