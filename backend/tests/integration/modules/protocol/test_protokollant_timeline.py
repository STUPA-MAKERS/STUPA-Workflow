"""Integration test: the minute taker persists and the timeline shows the name.

`patch` stores `protokollant_id`, and `list_timeline` must fill `protokollantName`.
Without the name the card and the list show no minute taker, so the value looks unsaved
although the database holds it.
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
    """Create an active member with `protocol.write` in the gremium, as a protokollant needs."""
    p = PrincipalRow(sub=f"s-{uuid.uuid4()}", display_name="Max P", email="m@x.de")
    session.add(p)
    await session.flush()
    role = GremiumRole(
        gremium_id=gremium.id,
        key=f"r-{uuid.uuid4()}",
        name_i18n={"de": "M"},
        permissions=["protocol.write"],
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
    """The protokollant persists and shows in the timeline, the reload path.

    The timeline must carry the name of the minute taker, or the card and the list look
    unsaved. The meeting date stays in the future relative to today, so the meeting
    appears in the upcoming branch of the timeline. A fixed date would drop out of that
    list once it passes, and the lookup would raise StopIteration.
    """
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    member = await _member(session, gremium)
    await session.commit()

    svc = MeetingService(session)
    admin = Principal(sub="adm", roles=["admin"])
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

    page = await svc.list_timeline(
        admin, direction="upcoming", cursor=None, limit=10, gremium_id=gremium.id
    )
    row = next(m for m in page.items if m.id == created.id)
    assert row.protokollant_id == member.id
    assert row.protokollant_name == "Max P"
