"""O6 with O23: a substitution of the lead blocks the own `present` report.

The meeting lead enters a substitution for a missing member during a live
meeting. While it exists, the member gets 409 `delegation_active` for an own
`present` report. When the member arrives, the lead revokes the substitution,
and the member can then report `present`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.modules.delegations.conftest import (
    act,
    gremium,
    make_api,
    meeting,
    member,
    person,
    pool_entry,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def api(migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    """Use the app wiring of the delegation tests (vote transfer switched on)."""
    application = make_api(migrated, monkeypatch)
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


@pytest.mark.parametrize("before", [None, "excused"])
async def test_own_present_waits_for_the_revoke(
    maker: async_sessionmaker[AsyncSession], api: FastAPI, before: str | None
) -> None:
    gid = await gremium(maker)
    lead, _ = await member(maker, gid, "Lead", ("session.manage", "vote.cast"))
    anna, a = await member(maker, gid, "Anna")
    _, b = await person(maker, "Bert")
    await pool_entry(maker, gid, b, for_member=a)
    mid = await meeting(maker, gid, status="live")
    me = f"/api/meetings/{mid}/attendance/me"
    with TestClient(api) as client:
        if before is not None:
            act(api, anna)
            assert client.put(me, json={"status": before}).status_code == 200
        act(api, lead)
        created = client.post(
            "/api/delegations",
            json={"meetingId": str(mid), "delegatorId": str(a), "delegateId": str(b)},
        )
        assert created.status_code == 201, created.text
        act(api, anna)
        blocked = client.put(me, json={"status": "present"})
        excused = client.put(me, json={"status": "excused"})
        act(api, lead)
        lead_set = client.put(f"/api/meetings/{mid}/attendance/{a}", json={"status": "present"})
        revoked = client.delete(f"/api/delegations/{created.json()['id']}")
        act(api, anna)
        present = client.put(me, json={"status": "present"})
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "delegation_active"
    # Only `present` is blocked; an excuse stays possible.
    assert excused.status_code == 200, excused.text
    assert lead_set.status_code == 409, lead_set.text
    assert revoked.status_code == 204, revoked.text
    assert present.status_code == 200, present.text
