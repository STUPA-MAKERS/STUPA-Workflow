"""The substitute pool on all six read paths.

The pool is the table `delegation_substitute`. The helpers in
`delegations.pool` are its only source. The six paths are:

1. the create (`viaPool`, no lead-time deadline),
2. the recipient list,
3. the meeting context,
4. the roster guard (`_assert_can_view_gremium`),
5. the meeting visibility (`_visible_gremium_ids`),
6. `/auth/me` (`in_substitute_pool`).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.models import Gremium
from app.modules.delegations.pool import (
    substitute_gremien,
    substitutes_for,
)
from tests.integration.modules.delegations.conftest import (
    act,
    gremium,
    meeting,
    member,
    person,
    pool_entry,
)

pytestmark = pytest.mark.integration


async def test_pool_substitute_on_all_six_paths(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    gid = await gremium(maker)
    # A lead time of a day: only a pool delegation may still be created.
    async with maker() as session:
        await session.execute(
            update(Gremium).where(Gremium.id == gid).values(delegation_lead_minutes=60 * 24 * 60)
        )
        await session.commit()
    mia_sub, mia = await member(maker, gid, "Mia")
    sam_sub, sam = await person(maker, "Sam")
    await pool_entry(maker, gid, sam, for_member=mia)
    mid = await meeting(maker, gid)

    with TestClient(api) as client:
        # 6. /auth/me
        act(api, sam_sub)
        me = client.get("/api/auth/me")
        # 5. meeting visibility of a pool substitute without a membership
        detail = client.get(f"/api/meetings/{mid}")
        timeline = client.get("/api/meetings")
        # 4. roster guard
        pool = client.get("/api/delegations/substitutes", params={"gremiumId": str(gid)})
        # 3. meeting context and 2. recipients of the member
        act(api, mia_sub)
        context = client.get(f"/api/delegations/meetings/{mid}/context")
        recipients = client.get(f"/api/delegations/meetings/{mid}/recipients")
        # 1. create: no lead-time deadline for a pool substitute
        created = client.post(
            "/api/delegations",
            json={"meetingId": str(mid), "delegateId": str(sam), "delegateVoting": True},
        )

    assert me.status_code == 200, me.text
    assert me.json()["in_substitute_pool"] is True
    assert detail.status_code == 200, detail.text
    assert timeline.status_code == 200, timeline.text
    assert str(mid) in {m["id"] for m in timeline.json()}
    assert pool.status_code == 200, pool.text
    assert context.status_code == 200, context.text
    ctx_sam = next(r for r in context.json()["recipients"] if r["principalId"] == str(sam))
    assert ctx_sam["viaPool"] is True
    assert "substituteGroupName" not in ctx_sam
    assert recipients.status_code == 200, recipients.text
    rec_sam = next(r for r in recipients.json() if r["principalId"] == str(sam))
    assert (rec_sam["viaPool"], rec_sam["isMember"]) == (True, False)
    assert created.status_code == 201, created.text
    assert created.json()["viaPool"] is True


async def test_outsider_has_no_pool_standing(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    gid = await gremium(maker)
    out_sub, _ = await person(maker, "Out")
    mid = await meeting(maker, gid)
    act(api, out_sub)
    with TestClient(api) as client:
        me = client.get("/api/auth/me")
        detail = client.get(f"/api/meetings/{mid}")
        groups = client.get(
            "/api/delegations/substitute-groups", params={"gremiumId": str(gid)}
        )
    assert me.json()["in_substitute_pool"] is False
    assert detail.status_code == 403
    # The faculty-group routes are gone.
    assert groups.status_code in {404, 405}


async def test_personal_and_gremium_wide_entries(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    gid = await gremium(maker)
    _, mia = await member(maker, gid, "Mia")
    _, ben = await member(maker, gid, "Ben")
    _, personal = await person(maker, "P")
    _, wide = await person(maker, "W")
    _, foreign = await person(maker, "F")
    other = await gremium(maker)
    await pool_entry(maker, gid, personal, for_member=mia)
    await pool_entry(maker, gid, wide)
    await pool_entry(maker, other, foreign, for_member=mia)
    async with maker() as session:
        assert await substitutes_for(session, gid, mia) == {personal, wide}
        # Ben has no personal entry: only the gremium-wide entry.
        assert await substitutes_for(session, gid, ben) == {wide}
        assert await substitute_gremien(session, personal) == {gid}
        assert await substitute_gremien(session, foreign) == {other}
        assert await substitute_gremien(session, wide) == {gid}
        # A member gives no pool standing.
        assert await substitute_gremien(session, mia) == set()
