"""A12/O16: the applicant sees the Gremium as the actor, not the member (real Postgres).

In the applicant view (magic link, or the creator without a read permission) the
timeline actor and the author of a member comment are the name of the Gremium of the
application. The own actions keep the applicant. A member still sees the names.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.service import ApplicationsService
from app.modules.auth.principal import Principal
from tests._support.read_models import (
    GREMIUM_NAME,
    MEMBER_NAME,
    OWNER_NAME,
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


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


async def _comment(
    maker: async_sessionmaker[AsyncSession], app_id: object, author: str | None, kind: str
) -> None:
    async with maker() as session:
        await ApplicationsService(session).add_comment(
            app_id,  # type: ignore[arg-type]
            author=author,
            author_kind=kind,
            body=f"von {author or 'applicant'}",
            visibility="public",
        )


async def test_magic_link_applicant_sees_the_gremium(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_read_world(maker)
    app_id = await create_app(maker, seed, actor="applicant")
    await fire(maker, app_id, seed.to_review_id, staff(seed))
    await _comment(maker, app_id, seed.member_sub, "principal")
    await _comment(maker, app_id, None, "applicant")

    api = build_read_api(migrated[1], monkeypatch)
    as_applicant(api, app_id)
    timeline = get_json(api, f"/api/applications/{app_id}/timeline")
    comments = get_json(api, f"/api/applications/{app_id}/comments")
    assert isinstance(timeline, list) and isinstance(comments, list)
    assert [e["actor"] for e in timeline] == ["applicant", GREMIUM_NAME]
    assert [(c["authorKind"], c["author"]) for c in comments] == [
        ("principal", GREMIUM_NAME),
        ("applicant", None),
    ]
    assert MEMBER_NAME not in str(timeline) + str(comments)

    # A member reads the same records with the names.
    as_principal(api, Principal(sub="reader", permissions={"application.read"}))
    timeline = get_json(api, f"/api/applications/{app_id}/timeline")
    comments = get_json(api, f"/api/applications/{app_id}/comments")
    assert isinstance(timeline, list) and isinstance(comments, list)
    assert [e["actor"] for e in timeline] == ["applicant", MEMBER_NAME]
    assert comments[0]["author"] == MEMBER_NAME


async def test_logged_in_creator_sees_the_gremium_and_the_own_name(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_read_world(maker)
    app_id = await create_app(maker, seed, actor=seed.owner_sub)
    await fire(maker, app_id, seed.to_review_id, staff(seed))
    await _comment(maker, app_id, seed.owner_sub, "principal")
    await _comment(maker, app_id, seed.member_sub, "principal")

    api = build_read_api(migrated[1], monkeypatch)
    as_principal(api, Principal(sub=seed.owner_sub, display_name=OWNER_NAME))
    timeline = get_json(api, f"/api/applications/{app_id}/timeline")
    comments = get_json(api, f"/api/applications/{app_id}/comments")
    assert isinstance(timeline, list) and isinstance(comments, list)
    assert [e["actor"] for e in timeline] == [OWNER_NAME, GREMIUM_NAME]
    assert [c["author"] for c in comments] == [OWNER_NAME, GREMIUM_NAME]
    assert [c["isOwn"] for c in comments] == [True, False]
