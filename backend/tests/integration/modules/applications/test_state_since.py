"""A9: `stateSince` is the time of the last status change (real Postgres).

The list, the tasks and the detail (the status page of the applicant) carry it. One
grouped subquery over `status_event` computes it for the list page.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.models import Application, StatusEvent
from app.modules.applications.service import ApplicationsService
from app.modules.auth.principal import Principal
from tests._support.read_models import (
    as_applicant,
    as_principal,
    build_read_api,
    create_app,
    fire,
    get_json,
    seed_read_world,
    staff,
)

pytestmark = pytest.mark.integration

_CREATED = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
_REVIEWED = datetime(2026, 9, 28, 14, 30, tzinfo=UTC)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


async def _pin_times(
    maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID, to_state_id: uuid.UUID
) -> None:
    """Set fixed times: the creation event at _CREATED, the review event at _REVIEWED."""
    async with maker() as session:
        await session.execute(
            update(StatusEvent)
            .where(StatusEvent.application_id == app_id, StatusEvent.from_state_id.is_(None))
            .values(at=_CREATED)
        )
        await session.execute(
            update(StatusEvent)
            .where(StatusEvent.application_id == app_id, StatusEvent.to_state_id == to_state_id)
            .values(at=_REVIEWED)
        )
        await session.execute(
            update(Application).where(Application.id == app_id).values(created_at=_CREATED)
        )
        await session.commit()


def _at(value: object) -> datetime:
    assert isinstance(value, str)
    return datetime.fromisoformat(value)


async def test_state_since_in_list_detail_and_tasks(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_read_world(maker)
    moved = await create_app(maker, seed, actor=seed.owner_sub, title="Bewegt")
    fresh = await create_app(maker, seed, actor=seed.owner_sub, title="Neu")
    await fire(maker, moved, seed.to_review_id, staff(seed))
    await _pin_times(maker, moved, seed.pruefung_id)
    await _pin_times(maker, fresh, seed.pruefung_id)

    api = build_read_api(migrated[1], monkeypatch)
    as_principal(api, Principal(sub="reader", permissions={"application.read"}))
    page = get_json(api, "/api/applications")
    assert isinstance(page, dict)
    since = {i["id"]: _at(i["stateSince"]) for i in page["items"]}
    assert since == {str(moved): _REVIEWED, str(fresh): _CREATED}

    detail = get_json(api, f"/api/applications/{moved}")
    assert isinstance(detail, dict)
    assert _at(detail["stateSince"]) == _REVIEWED

    # The status page of the applicant reads the same detail route.
    as_applicant(api, moved)
    status = get_json(api, f"/api/applications/{moved}")
    assert isinstance(status, dict)
    assert _at(status["stateSince"]) == _REVIEWED

    # Tasks: the staff member can fire `approve` from `pruefung`.
    async with maker() as session:
        tasks = await ApplicationsService(session).list_tasks(staff(seed))
    by_id = {t.id: t.state_since for t in tasks}
    assert by_id[moved] == _REVIEWED
    assert by_id[fresh] == _CREATED
