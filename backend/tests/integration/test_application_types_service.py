"""Integration (echte Postgres, testcontainers): ApplicationTypesService.

Beweist gegen ein echtes Schema (data-model §1): öffentlich werden nur Typen mit
aktiver Form-Version gelistet, Paging zählt korrekt, und die Admin-Sicht
(``include_inactive``/``admin``) liefert inaktive Typen + Zusatzfelder.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.application_types.service import ApplicationTypesService
from app.modules.forms.models import FormVersion

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _seed_type(
    session: AsyncSession,
    *,
    key: str,
    name: dict[str, str],
    has_budget: bool = False,
    active: bool = True,
) -> ApplicationType:
    """Antragstyp anlegen; bei ``active`` mit aktiver Form-Version verknüpft."""
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()

    app_type = ApplicationType(
        gremium_id=gremium.id, key=key, name_i18n=name, has_budget=has_budget
    )
    session.add(app_type)
    await session.flush()

    if active:
        version = FormVersion(application_type_id=app_type.id, version=1, active=True)
        session.add(version)
        await session.flush()
        app_type.active_form_version_id = version.id
        await session.flush()

    return app_type


async def test_public_lists_only_active_types(session: AsyncSession) -> None:
    await _seed_type(session, key="aktiv", name={"de": "Aktiv"})
    await _seed_type(session, key="inaktiv", name={"de": "Inaktiv"}, active=False)
    await session.commit()

    svc = ApplicationTypesService(session)
    page = await svc.list_types(lang="de", limit=50, offset=0)

    assert page.total == 1
    assert [i.key for i in page.items] == [None]  # public: kein key
    assert [i.name for i in page.items] == ["Aktiv"]
    assert page.items[0].active is True


async def test_admin_lists_inactive_with_extra_fields(session: AsyncSession) -> None:
    await _seed_type(session, key="aktiv", name={"de": "Aktiv"})
    await _seed_type(session, key="inaktiv", name={"de": "Inaktiv"}, active=False)
    await session.commit()

    svc = ApplicationTypesService(session)
    page = await svc.list_types(lang="de", limit=50, offset=0, include_inactive=True, admin=True)

    assert page.total == 2
    by_key = {i.key: i for i in page.items}
    assert by_key.keys() == {"aktiv", "inaktiv"}
    assert by_key["aktiv"].active is True
    assert by_key["inaktiv"].active is False
    assert by_key["inaktiv"].active_form_version_id is None
    assert by_key["aktiv"].gremium_id is not None


async def test_paging_limits_and_counts(session: AsyncSession) -> None:
    for n in range(3):
        await _seed_type(session, key=f"t{n}", name={"de": f"Typ {n}"})
    await session.commit()

    svc = ApplicationTypesService(session)
    page = await svc.list_types(lang="de", limit=2, offset=0)

    assert page.total == 3  # Total ignoriert das Limit
    assert len(page.items) == 2
    assert page.limit == 2

    page2 = await svc.list_types(lang="de", limit=2, offset=2)
    assert len(page2.items) == 1
