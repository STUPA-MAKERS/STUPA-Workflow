"""The timeline, the versions and the comments resolve each actor (real Postgres).

A member reads ``actorInfo``, ``changedByInfo`` and ``authorInfo``: the name of a
member, the applicant, a system key, or ``deleted`` for an unknown or anonymized
account. No raw ``sub`` leaves the server. The applicant view keeps the Gremium as
the actor of every action that the applicant did not do (A12, O16). One query
reads all principal names (no N+1).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.models import StatusEvent
from app.modules.applications.service import ApplicationsService
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from tests._support.read_models import (
    GREMIUM_NAME,
    IBAN,
    MEMBER_NAME,
    ReadSeed,
    as_applicant,
    as_principal,
    build_read_api,
    create_app,
    fire,
    get_json,
    patch,
    seed_read_world,
    staff,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine_async(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[Any]:
    eng = create_async_engine(migrated[1])
    yield eng
    await eng.dispose()


@pytest.fixture
def maker(engine_async: Any) -> async_sessionmaker[AsyncSession]:  # noqa: ANN401
    return async_sessionmaker(engine_async, expire_on_commit=False)


async def _add_event(
    maker: async_sessionmaker[AsyncSession],
    app_id: uuid.UUID,
    seed: ReadSeed,
    actor: str,
    minutes: int,
) -> None:
    async with maker() as session:
        session.add(
            StatusEvent(
                application_id=app_id,
                from_state_id=seed.pruefung_id,
                to_state_id=seed.pruefung_id,
                transition_id=None,
                actor=actor,
                at=datetime.now(UTC) + timedelta(minutes=minutes),
            )
        )
        await session.commit()


async def _add_anonymized(maker: async_sessionmaker[AsyncSession]) -> str:
    """Add an account that the privacy erasure emptied: no name, no email."""
    sub = f"gone-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        session.add(PrincipalRow(sub=sub, display_name=None, email=None))
        await session.commit()
    return sub


async def _principal_id(maker: async_sessionmaker[AsyncSession], sub: str) -> uuid.UUID:
    async with maker() as session:
        pid = await session.scalar(select(PrincipalRow.id).where(PrincipalRow.sub == sub))
    assert pid is not None
    return pid


async def _world(
    maker: async_sessionmaker[AsyncSession],
) -> tuple[ReadSeed, uuid.UUID, str, str]:
    """Seed one application with every kind of actor.

    Timeline: applicant, member, system:deadlines, system, unknown sub, anonymized.
    Versions: applicant, unknown sub.
    """
    seed = await seed_read_world(maker)
    app_id = await create_app(maker, seed, actor="applicant")
    await fire(maker, app_id, seed.to_review_id, staff(seed))
    unknown = str(uuid.uuid4())
    gone = await _add_anonymized(maker)
    await _add_event(maker, app_id, seed, "system:deadlines", 1)
    await _add_event(maker, app_id, seed, "system", 2)
    await _add_event(maker, app_id, seed, unknown, 3)
    await _add_event(maker, app_id, seed, gone, 4)
    await patch(
        maker,
        app_id,
        {"title": "Antrag", "iban": IBAN, "note": "zweite Notiz"},
        changed_by=unknown,
    )
    return seed, app_id, unknown, gone


async def test_member_view_resolves_every_actor(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, app_id, unknown, gone = await _world(maker)
    member_id = await _principal_id(maker, seed.member_sub)

    api = build_read_api(migrated[1], monkeypatch)
    as_principal(api, Principal(sub="reader", permissions={"application.read"}))
    timeline = get_json(api, f"/api/applications/{app_id}/timeline")
    versions = get_json(api, f"/api/applications/{app_id}/versions")
    assert isinstance(timeline, list) and isinstance(versions, list)

    # Only a member carries an id (for the avatar); no other actor does.
    assert [e["actorInfo"] for e in timeline] == [
        {"kind": "applicant", "key": None, "displayName": None, "principalId": None},
        {
            "kind": "principal",
            "key": None,
            "displayName": MEMBER_NAME,
            "principalId": str(member_id),
        },
        {"kind": "system", "key": "deadlines", "displayName": None, "principalId": None},
        {"kind": "system", "key": "auto", "displayName": None, "principalId": None},
        {"kind": "deleted", "key": None, "displayName": None, "principalId": None},
        {"kind": "deleted", "key": None, "displayName": None, "principalId": None},
    ]
    # The legacy string never carries a raw sub.
    assert [e["actor"] for e in timeline] == [
        "applicant",
        MEMBER_NAME,
        "system:deadlines",
        "system",
        None,
        None,
    ]
    assert [v["changedByInfo"]["kind"] for v in versions] == ["applicant", "deleted"]
    assert [v["changedBy"] for v in versions] == ["applicant", None]
    body = str(timeline) + str(versions)
    assert unknown not in body
    assert gone not in body


async def test_applicant_view_shows_the_gremium_for_all_other_actors(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, app_id, unknown, _ = await _world(maker)

    api = build_read_api(migrated[1], monkeypatch)
    as_applicant(api, app_id)
    timeline = get_json(api, f"/api/applications/{app_id}/timeline")
    versions = get_json(api, f"/api/applications/{app_id}/versions")
    assert isinstance(timeline, list) and isinstance(versions, list)

    # The applicant view holds no member id.
    gremium = {"kind": "gremium", "key": None, "displayName": GREMIUM_NAME, "principalId": None}
    assert [e["actorInfo"] for e in timeline] == [
        {"kind": "applicant", "key": None, "displayName": None, "principalId": None},
        gremium,
        gremium,
        gremium,
        gremium,
        gremium,
    ]
    assert [v["changedByInfo"] for v in versions] == [
        {"kind": "applicant", "key": None, "displayName": None, "principalId": None},
        gremium,
    ]
    body = str(timeline) + str(versions)
    assert MEMBER_NAME not in body
    assert unknown not in body


async def test_comment_of_an_unknown_author_shows_no_sub(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_read_world(maker)
    app_id = await create_app(maker, seed, actor="applicant")
    unknown = str(uuid.uuid4())
    async with maker() as session:
        created = await ApplicationsService(session).add_comment(
            app_id,
            author=unknown,
            author_kind="principal",
            body="alt",
            visibility="public",
        )
        await ApplicationsService(session).add_comment(
            app_id,
            author=seed.member_sub,
            author_kind="principal",
            body="neu",
            visibility="public",
        )
    assert created.author is None
    assert created.author_info is not None and created.author_info.kind == "deleted"

    api = build_read_api(migrated[1], monkeypatch)
    as_principal(api, Principal(sub="reader", permissions={"application.read"}))
    comments = get_json(api, f"/api/applications/{app_id}/comments")
    assert isinstance(comments, list)
    assert [(c["author"], c["authorInfo"]["kind"]) for c in comments] == [
        (None, "deleted"),
        (MEMBER_NAME, "principal"),
    ]
    # The member author carries the id for the avatar, the unknown one none.
    member_id = await _principal_id(maker, seed.member_sub)
    assert [c["authorInfo"]["principalId"] for c in comments] == [None, str(member_id)]
    assert unknown not in str(comments)


async def test_timeline_reads_the_principal_names_in_one_query(
    engine_async: Any,  # noqa: ANN401
    maker: async_sessionmaker[AsyncSession],
) -> None:
    seed, app_id, _, _ = await _world(maker)
    # More member events: the query count must not grow with them.
    for i in range(5):
        await _add_event(maker, app_id, seed, seed.member_sub, 10 + i)

    statements: list[str] = []

    def _count(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        if "FROM principal" in statement:
            statements.append(statement)

    event.listen(engine_async.sync_engine, "before_cursor_execute", _count)
    try:
        async with maker() as session:
            await ApplicationsService(session).timeline(app_id)
    finally:
        event.remove(engine_async.sync_engine, "before_cursor_execute", _count)
    assert len(statements) == 1
