"""A12/O16: the applicant sees the Gremium as the actor, not the member (real Postgres).

In the applicant view (magic link, or the creator who is no member) the timeline
actor and the author of a member comment are the name of the Gremium of the
application. The own actions keep the applicant. A member still sees the names. A
creator who reads through the Gremium read scope, or who holds a member right, is a
member.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.router import get_comment_mail_sender
from app.modules.applications.service import ApplicationsService
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from tests._support.read_models import (
    GREMIUM_NAME,
    IBAN,
    MEMBER_NAME,
    OWNER_NAME,
    ReadSeed,
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


async def _set_creator_email(
    maker: async_sessionmaker[AsyncSession], sub: str, email: str
) -> None:
    async with maker() as session:
        await session.execute(
            update(PrincipalRow).where(PrincipalRow.sub == sub).values(email=email)
        )
        await session.commit()


async def test_magic_link_applicant_sees_the_gremium_for_a_creator_of_another_email(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F23: a member submits for another email. The applicant sees no member name."""
    seed = await seed_read_world(maker)
    await _set_creator_email(maker, seed.owner_sub, "member@example.org")
    app_id = await create_app(maker, seed, actor=seed.owner_sub)
    await _comment(maker, app_id, seed.owner_sub, "principal")

    api = build_read_api(migrated[1], monkeypatch)
    as_applicant(api, app_id)
    timeline = get_json(api, f"/api/applications/{app_id}/timeline")
    versions = get_json(api, f"/api/applications/{app_id}/versions")
    comments = get_json(api, f"/api/applications/{app_id}/comments")
    assert isinstance(timeline, list) and isinstance(versions, list)
    assert isinstance(comments, list)
    assert [e["actor"] for e in timeline] == [GREMIUM_NAME]
    assert [v["changedBy"] for v in versions] == [GREMIUM_NAME]
    assert [c["author"] for c in comments] == [GREMIUM_NAME]
    assert OWNER_NAME not in str(timeline) + str(versions) + str(comments)


async def test_magic_link_applicant_keeps_the_own_name_as_creator(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The creator submitted with the own account email: the magic link is the same person."""
    seed = await seed_read_world(maker)
    # The applicant email of `create_app`, with another case.
    await _set_creator_email(maker, seed.owner_sub, "Antrag@Example.org")
    app_id = await create_app(maker, seed, actor=seed.owner_sub)

    api = build_read_api(migrated[1], monkeypatch)
    as_applicant(api, app_id)
    timeline = get_json(api, f"/api/applications/{app_id}/timeline")
    assert isinstance(timeline, list)
    assert [e["actor"] for e in timeline] == [OWNER_NAME]


async def _internal_and_public(
    maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID, author: str
) -> None:
    async with maker() as session:
        for visibility in ("internal", "public"):
            await ApplicationsService(session).add_comment(
                app_id,
                author=author,
                author_kind="principal",
                body=f"{visibility} note",
                visibility=visibility,
            )


async def _no_mail(*_args: object) -> None:
    return None


def _assert_reads_as_member(api: FastAPI, app_id: uuid.UUID, own_name: str) -> None:
    """Internal comments, member names in the timeline, and the full version data."""
    comments = get_json(api, f"/api/applications/{app_id}/comments")
    timeline = get_json(api, f"/api/applications/{app_id}/timeline")
    versions = get_json(api, f"/api/applications/{app_id}/versions")
    assert isinstance(comments, list) and isinstance(timeline, list)
    assert isinstance(versions, list)
    assert sorted(c["body"] for c in comments) == ["internal note", "public note"]
    assert [e["actor"] for e in timeline] == [own_name, MEMBER_NAME]
    assert GREMIUM_NAME not in [e["actor"] for e in timeline]
    # The creator reads the own isPII fields, and as a member the values too.
    assert versions[0]["data"]["iban"] == IBAN
    assert versions[0]["changedBy"] == own_name
    # No comment mail: the test checks the access, not the delivery.
    api.dependency_overrides[get_comment_mail_sender] = lambda: _no_mail
    with TestClient(api) as client:
        resp = client.post(
            f"/api/applications/{app_id}/comments",
            json={"body": "intern", "visibility": "internal"},
        )
    assert resp.status_code == 201, resp.text


async def _created_by(
    maker: async_sessionmaker[AsyncSession], seed: ReadSeed, sub: str, *, in_scope: bool
) -> uuid.UUID:
    app_id = await create_app(maker, seed, actor=sub, in_read_scope=in_scope)
    await fire(maker, app_id, seed.to_review_id, staff(seed))
    await _internal_and_public(maker, app_id, seed.member_sub)
    return app_id


async def test_creator_in_the_gremium_read_scope_reads_as_a_member(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F23: a member submits for a student and still reads the own Gremium work.

    The member has no global permission and reads through the view cost centre of
    the Gremium. The Gremium read scope comes before the creator path.
    """
    seed = await seed_read_world(maker)
    app_id = await _created_by(maker, seed, seed.member_sub, in_scope=True)

    api = build_read_api(migrated[1], monkeypatch)
    as_principal(api, Principal(sub=seed.member_sub, display_name=MEMBER_NAME))
    _assert_reads_as_member(api, app_id, MEMBER_NAME)
    detail = get_json(api, f"/api/applications/{app_id}")
    assert isinstance(detail, dict)
    assert detail["data"]["iban"] == IBAN
    assert detail["hiddenKeys"] == []


@pytest.mark.parametrize(
    "perm",
    ["application.manage", "application.transition", "application.edit_any"],
)
async def test_creator_with_a_member_right_reads_as_a_member(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    perm: str,
) -> None:
    """A creator who works on applications is no applicant, also outside the scope."""
    seed = await seed_read_world(maker)
    app_id = await _created_by(maker, seed, seed.owner_sub, in_scope=False)

    api = build_read_api(migrated[1], monkeypatch)
    as_principal(api, Principal(sub=seed.owner_sub, display_name=OWNER_NAME, permissions={perm}))
    _assert_reads_as_member(api, app_id, OWNER_NAME)


async def test_creator_without_a_member_right_outside_the_scope_reads_as_applicant(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The counterpart: a right that is no member right keeps the applicant view."""
    seed = await seed_read_world(maker)
    app_id = await _created_by(maker, seed, seed.owner_sub, in_scope=False)

    api = build_read_api(migrated[1], monkeypatch)
    as_principal(
        api,
        Principal(sub=seed.owner_sub, display_name=OWNER_NAME, permissions={"application.share"}),
    )
    comments = get_json(api, f"/api/applications/{app_id}/comments")
    timeline = get_json(api, f"/api/applications/{app_id}/timeline")
    assert isinstance(comments, list) and isinstance(timeline, list)
    assert [c["body"] for c in comments] == ["public note"]
    assert [e["actor"] for e in timeline] == [OWNER_NAME, GREMIUM_NAME]
