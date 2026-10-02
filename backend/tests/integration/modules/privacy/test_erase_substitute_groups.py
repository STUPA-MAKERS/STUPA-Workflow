"""Z5: the erasure of a principal deletes the rows in the faculty groups.

The principal row stays as a pseudonym, so the CASCADE of the foreign key does
not apply. `PrincipalService.erase` deletes the rows explicitly. The rows of
other people stay.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.models import Gremium
from app.modules.auth.models import Principal
from app.modules.delegations.models import SubstituteGroup, SubstituteGroupMember
from app.modules.privacy.service import PrincipalService
from tests.integration.modules.delegations.conftest import maker  # noqa: F401

pytestmark = pytest.mark.integration


async def test_erase_deletes_the_group_rows(maker: async_sessionmaker[AsyncSession]) -> None:  # noqa: F811
    async with maker() as session:
        gremium = Gremium(name="StuPa", slug=f"g-{uuid.uuid4().hex[:8]}")
        gone = Principal(sub=f"gone-{uuid.uuid4()}", display_name="Gone", active=True)
        stays = Principal(sub=f"stays-{uuid.uuid4()}", display_name="Stays", active=True)
        session.add_all([gremium, gone, stays])
        await session.flush()
        first = SubstituteGroup(gremium_id=gremium.id, name_i18n={"de": "A"})
        second = SubstituteGroup(gremium_id=gremium.id, name_i18n={"de": "B"})
        session.add_all([first, second])
        await session.flush()
        session.add_all(
            [
                SubstituteGroupMember(
                    group_id=first.id, principal_id=gone.id, gremium_id=gremium.id, kind="member"
                ),
                SubstituteGroupMember(
                    group_id=second.id,
                    principal_id=gone.id,
                    gremium_id=gremium.id,
                    kind="substitute",
                ),
                SubstituteGroupMember(
                    group_id=first.id,
                    principal_id=stays.id,
                    gremium_id=gremium.id,
                    kind="substitute",
                ),
            ]
        )
        await session.commit()
        gone_id, stays_id, gremium_id = gone.id, stays.id, gremium.id

    async with maker() as session:
        await PrincipalService(session).erase(gone_id, actor="admin")

    async with maker() as session:
        rows = (
            await session.execute(
                select(SubstituteGroupMember.principal_id, SubstituteGroupMember.kind).where(
                    SubstituteGroupMember.gremium_id == gremium_id
                )
            )
        ).all()
        assert [(pid, kind) for pid, kind in rows] == [(stays_id, "substitute")]
        assert await session.get(Principal, gone_id) is not None
