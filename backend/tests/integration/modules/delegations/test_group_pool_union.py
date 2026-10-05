"""Z5: the faculty groups join the substitute pool on all six read paths.

The pool is the union of `delegation_substitute` and the faculty groups. The
helpers in `delegations.pool` are its only source. The six paths are:

1. the create (`viaPool`, no lead-time deadline),
2. the recipient list,
3. the meeting context,
4. the roster guard (`_assert_can_view_gremium`),
5. the meeting visibility (`_visible_gremium_ids`),
6. `/auth/me` (`in_substitute_pool`).

A member of a faculty group counts only while the gremium membership is active.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.models import Gremium
from app.modules.delegations.models import DelegationSubstitute
from app.modules.delegations.pool import (
    substitute_gremien,
    substitutes_for,
)
from tests.integration.modules.delegations.conftest import (
    act,
    faculty_group,
    gremium,
    meeting,
    member,
    person,
)

pytestmark = pytest.mark.integration


async def test_group_substitute_on_all_six_paths(
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
    await faculty_group(maker, gid, members=(mia,), substitutes=(sam,), name="Informatik")
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
        groups = client.get(
            "/api/delegations/substitute-groups", params={"gremiumId": str(gid)}
        )
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
    assert groups.status_code == 200, groups.text
    assert context.status_code == 200, context.text
    ctx_sam = next(r for r in context.json()["recipients"] if r["principalId"] == str(sam))
    assert ctx_sam["viaPool"] is True
    assert ctx_sam["substituteGroupName"] == {"de": "Informatik"}
    assert recipients.status_code == 200, recipients.text
    rec_sam = next(r for r in recipients.json() if r["principalId"] == str(sam))
    assert (rec_sam["viaPool"], rec_sam["isMember"]) == (True, False)
    assert rec_sam["substituteGroupName"] == {"de": "Informatik"}
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
    assert groups.status_code == 403


async def test_union_with_personal_and_gremium_wide_entries(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    gid = await gremium(maker)
    _, mia = await member(maker, gid, "Mia")
    _, ben = await member(maker, gid, "Ben")
    _, group_sub = await person(maker, "G")
    _, personal = await person(maker, "P")
    _, wide = await person(maker, "W")
    _, foreign = await person(maker, "F")
    await faculty_group(maker, gid, members=(mia,), substitutes=(group_sub,))
    other = await gremium(maker)
    await faculty_group(maker, other, members=(mia,), substitutes=(foreign,))
    async with maker() as session:
        session.add_all(
            [
                DelegationSubstitute(
                    gremium_id=gid, member_principal_id=mia, substitute_principal_id=personal
                ),
                DelegationSubstitute(
                    gremium_id=gid, member_principal_id=None, substitute_principal_id=wide
                ),
            ]
        )
        await session.commit()
    async with maker() as session:
        assert await substitutes_for(session, gid, mia) == {group_sub, personal, wide}
        # Ben is in no group: only the gremium-wide entry.
        assert await substitutes_for(session, gid, ben) == {wide}
        # Without the groups (O6 lead entry): the personal and gremium-wide entries.
        assert await substitutes_for(session, gid, mia, include_groups=False) == {
            personal,
            wide,
        }
        assert await substitute_gremien(session, group_sub) == {gid}
        assert await substitute_gremien(session, foreign) == {other}
        assert await substitute_gremien(session, wide) == {gid}
        # A member row gives no pool standing.
        assert await substitute_gremien(session, mia) == set()


async def test_inactive_member_does_not_count(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    gid = await gremium(maker)
    _, gone = await member(maker, gid, "Gone", ended=True)
    _, never = await person(maker, "Never")
    _, sub = await person(maker, "Sub")
    await faculty_group(maker, gid, members=(gone,), substitutes=(sub,))
    await faculty_group(maker, gid, members=(never,), substitutes=(sub,), name="Technik")
    async with maker() as session:
        now = datetime.now(UTC)
        assert await substitutes_for(session, gid, gone, now) == set()
        assert await substitutes_for(session, gid, never, now) == set()
    act(api, "office", permissions={"admin.delegations"})
    with TestClient(api) as client:
        groups = client.get(
            "/api/delegations/substitute-groups", params={"gremiumId": str(gid)}
        ).json()
    states = {
        m["displayName"]: m["active"] for g in groups for m in g["members"] if m["kind"] == "member"
    }
    assert states == {"Gone": False, "Never": False}
