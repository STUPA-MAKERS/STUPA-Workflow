"""Integration test: the minute taker persists and the timeline shows the name.

Regression (#protokollant-save): `patch` stored `protokollant_id` correctly, but
`list_timeline` never filled `protokollantName`. The card and the list showed no minute
taker, so the value looked unsaved although the database held it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, time, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.schemas import MeetingCreate, MeetingPatch
from app.modules.livevote.service import MeetingService

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _member(session: AsyncSession, gremium: Gremium) -> PrincipalRow:
    p = PrincipalRow(sub=f"s-{uuid.uuid4()}", display_name="Max P", email="m@x.de")
    session.add(p)
    await session.flush()
    role = GremiumRole(
        gremium_id=gremium.id, key=f"r-{uuid.uuid4()}", name_i18n={"de": "M"}
    )
    session.add(role)
    await session.flush()
    session.add(
        GremiumMembership(
            principal_id=p.id,
            gremium_id=gremium.id,
            gremium_role_id=role.id,
            valid_from=None,
            valid_until=None,
        )
    )
    await session.flush()
    return p


async def test_protokollant_persists_and_shows_in_timeline(session: AsyncSession) -> None:
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    member = await _member(session, gremium)
    await session.commit()

    svc = MeetingService(session)
    admin = Principal(sub="adm", roles=["admin"])
    # The date stays in the future relative to today, so the meeting appears in the
    # `direction="upcoming"` branch of the timeline. A hardcoded date would be a time
    # bomb. As soon as it moves into the past, the meeting drops out of the upcoming
    # list and `next(...)` below raises StopIteration.
    created = await svc.create(
        MeetingCreate(
            gremiumId=gremium.id,
            title="GV",
            date=date.today() + timedelta(days=7),
            startTime=time(18, 0),
        ),
        admin,
    )

    patched = await svc.patch(
        created.id,
        MeetingPatch.model_validate({"protokollantId": str(member.id)}),
        admin,
    )
    assert patched.protokollant_id == member.id
    assert patched.protokollant_name == "Max P"

    # The timeline is the reload path. It must carry the name of the minute taker.
    # Otherwise the card and the list look unsaved.
    page = await svc.list_timeline(
        admin, direction="upcoming", cursor=None, limit=10, gremium_id=gremium.id
    )
    row = next(m for m in page.items if m.id == created.id)
    assert row.protokollant_id == member.id
    assert row.protokollant_name == "Max P"
