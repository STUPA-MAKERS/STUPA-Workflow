"""Integration (echte Postgres, testcontainers): Kalender-Feed (#ics).

Beweist gegen das migrierte Schema:
* ``calendar_token`` rotiert + Round-Trip ``principal_by_calendar_token`` /
  ``get_calendar_token``.
* ``member_meetings`` liefert **nur** datierte Sitzungen der Mitglieds-Gremien
  (Fremd-Gremium + datumslose Sitzung werden ausgelassen) — echter SQL-Join.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date as _date
from datetime import time as _time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.calendar import service
from app.modules.livevote.models import Meeting

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str]) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _member_of(session: AsyncSession, gremium: Gremium) -> PrincipalRow:
    p = PrincipalRow(sub=f"s-{uuid.uuid4()}", display_name="Max", email="m@x.de")
    session.add(p)
    await session.flush()
    role = GremiumRole(gremium_id=gremium.id, key=f"r-{uuid.uuid4()}", name_i18n={"de": "M"})
    session.add(role)
    await session.flush()
    session.add(
        GremiumMembership(principal_id=p.id, gremium_id=gremium.id, gremium_role_id=role.id)
    )
    await session.flush()
    return p


async def test_calendar_token_round_trip(session: AsyncSession) -> None:
    gremium = Gremium(name="StuPa", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    member = await _member_of(session, gremium)
    await session.commit()

    token = await service.rotate_calendar_token(session, member.sub)
    await session.commit()
    assert token

    assert await service.get_calendar_token(session, member.sub) == token
    resolved = await service.principal_by_calendar_token(session, token)
    assert resolved is not None and resolved.sub == member.sub
    # Unbekannter Token → None.
    assert await service.principal_by_calendar_token(session, "nope") is None


async def test_member_meetings_filters(session: AsyncSession) -> None:
    home = Gremium(name="StuPa", slug=f"g-{uuid.uuid4()}")
    other = Gremium(name="AStA", slug=f"g-{uuid.uuid4()}")
    session.add_all([home, other])
    await session.flush()
    member = await _member_of(session, home)
    session.add_all(
        [
            Meeting(
                gremium_id=home.id,
                title="GV",
                date=_date(2026, 7, 1),
                start_time=_time(18, 0),
                status="planned",
            ),
            # Datumslos → ausgelassen.
            Meeting(gremium_id=home.id, title="ohne Datum", status="planned"),
            # Fremd-Gremium → ausgelassen.
            Meeting(
                gremium_id=other.id,
                title="fremd",
                date=_date(2026, 7, 2),
                status="planned",
            ),
        ]
    )
    await session.commit()

    pairs = await service.member_meetings(session, member.sub)
    assert [(m.title, name) for m, name in pairs] == [("GV", "StuPa")]
