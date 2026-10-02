"""A3: every timeline event carries the label of the fired transition (real Postgres).

The creation event and a revert fire no transition, so their label is null.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.auth.principal import Principal
from tests._support.read_models import (
    as_principal,
    build_read_api,
    create_app,
    fire,
    get_json,
    seed_read_world,
    staff,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


async def test_timeline_events_carry_the_transition_label(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_read_world(maker)
    app_id = await create_app(maker, seed, actor=seed.owner_sub)
    await fire(maker, app_id, seed.to_review_id, staff(seed))
    await fire(maker, app_id, seed.approve_id, staff(seed))

    api = build_read_api(migrated[1], monkeypatch)
    as_principal(api, Principal(sub="reader", permissions={"application.read"}))
    events = get_json(api, f"/api/applications/{app_id}/timeline")
    assert isinstance(events, list)
    assert [e["transitionLabel"] for e in events] == [
        None,  # the creation fires no transition
        {"de": "Zur Prüfung", "en": "To review"},
        {"de": "Genehmigen", "en": "Approve"},
    ]
    assert [e["toState"]["key"] for e in events] == ["eingang", "pruefung", "genehmigt"]
