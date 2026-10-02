"""F8, O13, O2, F12: the protocol is finalized once, after the close, with an audit.

* A live meeting gives 409 `meeting_not_closed`, and the protocol stays a draft.
* A closed meeting finalizes. The start writes `protocol_finalize`.
* A second finalize gives 409 `protocol_not_draft`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.livevote.models import Meeting
from app.modules.protocol.models import Protocol
from tests.integration.modules.livevote.conftest import ADMIN_SUB, audit_actions, seed

pytestmark = pytest.mark.integration


async def test_finalize_only_after_the_close_and_only_once(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", items=1, protocol="draft")
    assert s.protocol_id is not None
    url = f"/api/protocols/{s.protocol_id}/finalize"
    with TestClient(api) as client:
        live = client.post(url)
        assert live.status_code == 409, live.text
        assert live.json()["code"] == "meeting_not_closed"
        async with maker() as session:
            protocol = await session.get(Protocol, s.protocol_id)
            assert protocol is not None and protocol.status == "draft"
        closed = client.patch(f"/api/meetings/{s.meeting_id}", json={"status": "closed"})
        assert closed.status_code == 200, closed.text
        done = client.post(url)
        again = client.post(url)
    # Without Redis the request renders synchronously; without storage no PDF exists.
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "final"
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "protocol_not_draft"
    entries = [
        e for e in await audit_actions(maker, target_id=s.protocol_id)
        if e.action == "protocol_finalize"
    ]
    assert len(entries) == 1
    assert entries[0].actor == ADMIN_SUB
    assert entries[0].data == {"meetingId": str(s.meeting_id), "gremiumId": str(s.gremium_id)}


async def test_planned_meeting_cannot_finalize(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="planned", items=0, protocol="draft")
    with TestClient(api) as client:
        resp = client.post(f"/api/protocols/{s.protocol_id}/finalize")
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "meeting_not_closed"
    async with maker() as session:
        meeting = await session.get(Meeting, s.meeting_id)
        assert meeting is not None and meeting.status == "planned"
