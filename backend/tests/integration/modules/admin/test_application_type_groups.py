"""Integration (real Postgres): the groups of Antragsarten and their order.

Specs 001180 (groups, the delete keeps the types), 001181 (the public group list) and
001183 (the manual order of groups and types, new rows at the end).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.schemas import (
    ApplicationTypeCreate,
    ApplicationTypeGroupCreate,
    ApplicationTypeGroupUpdate,
    ApplicationTypeUpdate,
)
from app.modules.admin.service import ConfigService
from app.modules.application_types.models import ApplicationType
from app.modules.application_types.service import ApplicationTypesService
from app.modules.forms.models import FormVersion
from app.shared.errors import NotFoundError

pytestmark = pytest.mark.integration

_ACTOR = "oidc|admin"


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _group(svc: ConfigService, name: str, text: str = "") -> uuid.UUID:
    created = await svc.create_application_type_group(
        ApplicationTypeGroupCreate.model_validate(
            {"nameI18n": {"de": name}, "textI18n": {"de": text} if text else {}}
        ),
        _ACTOR,
    )
    return created.id


async def _type(svc: ConfigService, name: str, group_id: uuid.UUID | None) -> uuid.UUID:
    created = await svc.create_application_type(
        ApplicationTypeCreate.model_validate(
            {
                "key": f"{name.lower()}-{uuid.uuid4().hex[:8]}",
                "nameI18n": {"de": name},
                "groupId": str(group_id) if group_id else None,
            }
        ),
        _ACTOR,
    )
    return created.id


async def _offer(session: AsyncSession, type_id: uuid.UUID) -> None:
    """Give a type an active form version, so the public list offers it."""
    version = FormVersion(application_type_id=type_id, version=1, active=True)
    session.add(version)
    await session.flush()
    row = await session.get(ApplicationType, type_id)
    assert row is not None
    row.active_form_version_id = version.id
    await session.commit()


async def test_group_crud_and_delete_keeps_the_types(session: AsyncSession) -> None:
    svc = ConfigService(session)
    group = await _group(svc, "Projektanträge", "Für **Projekte**")
    first = await _type(svc, "VSM", group)
    second = await _type(svc, "QSM", group)
    listed = {t.id: t for t in await svc.list_application_types()}
    assert listed[first].group_id == group
    assert (listed[first].position, listed[second].position) == (0, 1)

    renamed = await svc.update_application_type_group(
        group,
        ApplicationTypeGroupUpdate.model_validate({"nameI18n": {"de": "Projekte"}}),
        _ACTOR,
    )
    assert renamed.name_i18n == {"de": "Projekte"}
    assert renamed.text_i18n == {"de": "Für **Projekte**"}

    await svc.delete_application_type_group(group, _ACTOR)
    after = {t.id: t for t in await svc.list_application_types()}
    assert after[first].group_id is None
    assert after[second].group_id is None
    assert after[first].position < after[second].position
    with pytest.raises(NotFoundError):
        await svc.delete_application_type_group(group, _ACTOR)


async def test_group_needs_a_german_name() -> None:
    with pytest.raises(ValueError, match="German name"):
        ApplicationTypeGroupCreate.model_validate({"nameI18n": {"en": "Projects"}})


async def test_move_groups_and_types(session: AsyncSession) -> None:
    svc = ConfigService(session)
    before = [g.id for g in await svc.list_application_type_groups()]
    a = await _group(svc, "A")
    b = await _group(svc, "B")
    assert [g.id for g in await svc.list_application_type_groups()] == [*before, a, b]
    moved = await svc.move_application_type_group(b, -1, _ACTOR)
    assert [g.id for g in moved][-2:] == [b, a]
    first = await svc.list_application_type_groups()
    unchanged = await svc.move_application_type_group(first[0].id, -1, _ACTOR)
    assert [g.id for g in unchanged] == [g.id for g in first]

    one = await _type(svc, "Eins", a)
    two = await _type(svc, "Zwei", a)
    await svc.move_application_type(two, -1, _ACTOR)
    order = [t.id for t in await svc.list_application_types() if t.group_id == a]
    assert order == [two, one]


async def test_type_changes_group_and_goes_to_the_end(session: AsyncSession) -> None:
    svc = ConfigService(session)
    a = await _group(svc, "A")
    b = await _group(svc, "B")
    in_b = await _type(svc, "B1", b)
    moving = await _type(svc, "A1", a)
    updated = await svc.update_application_type(
        moving, ApplicationTypeUpdate.model_validate({"groupId": str(b)}), _ACTOR
    )
    assert updated.group_id == b
    listed = {t.id: t for t in await svc.list_application_types()}
    assert listed[moving].position > listed[in_b].position
    cleared = await svc.update_application_type(
        moving, ApplicationTypeUpdate.model_validate({"groupId": None}), _ACTOR
    )
    assert cleared.group_id is None
    kept = await svc.update_application_type(
        in_b, ApplicationTypeUpdate.model_validate({"hasBudget": False}), _ACTOR
    )
    assert kept.group_id == b
    with pytest.raises(NotFoundError):
        await svc.update_application_type(
            moving, ApplicationTypeUpdate.model_validate({"groupId": str(uuid.uuid4())}), _ACTOR
        )


async def test_public_list_follows_the_group_order(session: AsyncSession) -> None:
    svc = ConfigService(session)
    for existing in await svc.list_application_type_groups():
        await svc.delete_application_type_group(existing.id, _ACTOR)
    first = await _group(svc, "Erste", "Text eins")
    second = await _group(svc, "Zweite")
    loose = await _type(svc, "Lose", None)
    late = await _type(svc, "Spaet", second)
    early = await _type(svc, "Frueh", first)
    for type_id in (loose, late, early):
        await _offer(session, type_id)

    public = ApplicationTypesService(session)
    page = await public.list_types(limit=200, offset=0)
    ours = [t.id for t in page.items if t.id in {loose, late, early}]
    assert ours == [early, late, loose]
    assert {t.id: t.group_id for t in page.items}[early] == first

    groups = await public.list_groups(lang="en")
    assert [(g.id, g.name, g.text) for g in groups] == [
        (first, "Erste", "Text eins"),
        (second, "Zweite", ""),
    ]
