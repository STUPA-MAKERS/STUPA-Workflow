"""Bulk actions of the Antrag list on a real Postgres (specs 001700-001703).

§ 001701 the options are the targets that every selected Antrag reaches, and the fire
checks each Antrag again. § 001702 a bulk message adds one public comment and one mail
per Antrag. § 001703 each Antrag runs on its own, and the result names each outcome.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_principal
from app.modules.applications.models import Application, Comment
from app.modules.applications.router import get_comment_mail_sender, get_magic_link_sender
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.auth.principal import Principal
from app.settings import Settings
from tests._support.guest_apps import GuestSeed, build_api, guest_settings, seed_guest_flow

pytestmark = pytest.mark.integration

_MANAGER = Principal(
    sub="manager-sub",
    roles=["member"],
    permissions={"application.read", "application.manage", "application.transition"},
    email="manager@example.org",
)
_MEMBER = Principal(
    sub="member-sub",
    roles=["member"],
    permissions={"application.read", "application.transition"},
    email="member@example.org",
)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return guest_settings(migrated[1])


@pytest.fixture
async def seed(maker: async_sessionmaker[AsyncSession]) -> GuestSeed:
    return await seed_guest_flow(maker)


async def _create(maker: async_sessionmaker[AsyncSession], seed: GuestSeed, n: int) -> uuid.UUID:
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(seed.type_id),
            "data": {"title": f"Antrag {n}"},
            "applicantEmail": f"a{n}@example.org",
        }
    )
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            payload, actor=f"owner-{n}", email_confirmed=True
        )
        return app.id


def _client(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    principal: Principal,
    mails: list[uuid.UUID] | None = None,
) -> TestClient:
    async def _no_mail(*_args: object) -> None:
        return None

    async def _comment_mail(_settings: object, app_id: uuid.UUID, *_rest: object) -> None:
        (mails if mails is not None else []).append(app_id)

    api = build_api(migrated[1], settings, monkeypatch)
    api.dependency_overrides[get_current_principal] = lambda: principal
    api.dependency_overrides[get_magic_link_sender] = lambda: _no_mail
    api.dependency_overrides[get_comment_mail_sender] = lambda: _comment_mail
    return TestClient(api)


async def test_a_bulk_transition_runs_per_antrag(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 001701, § 001703: one Antrag that moved before the fire fails on its own."""
    ids = [await _create(maker, seed, n) for n in range(3)]
    client = _client(migrated, settings, monkeypatch, _MANAGER)
    body = {"applicationIds": [str(i) for i in ids]}

    options = client.post("/api/bulk/applications/transitions", json=body)
    assert options.status_code == 200, options.text
    assert [o["toStateId"] for o in options.json()] == [str(seed.locked_state_id)]

    first = client.post(
        "/api/bulk/applications/transition",
        json={"applicationIds": [str(ids[0])], "toStateId": str(seed.locked_state_id)},
    )
    assert first.json()["results"][0]["ok"] is True
    assert client.post("/api/bulk/applications/transitions", json=body).json() == []

    res = client.post(
        "/api/bulk/applications/transition",
        json={**body, "toStateId": str(seed.locked_state_id)},
    )
    assert res.status_code == 200, res.text
    results = res.json()["results"]
    assert [r["ok"] for r in results] == [False, True, True]
    assert results[0]["code"] == "transition_not_available"
    assert results[0]["error"]
    async with maker() as session:
        states = {
            a.id: a.current_state_id
            for a in (
                await session.scalars(select(Application).where(Application.id.in_(ids)))
            ).all()
        }
    assert set(states.values()) == {seed.locked_state_id}


async def test_a_bulk_message_adds_one_public_comment_and_mail_each(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 001702: three Anträge, three public comments, three mails."""
    ids = [await _create(maker, seed, n) for n in range(3)]
    mails: list[uuid.UUID] = []
    client = _client(migrated, settings, monkeypatch, _MANAGER, mails)
    unknown = uuid.uuid4()
    res = client.post(
        "/api/bulk/applications/comments",
        json={
            "applicationIds": [*map(str, ids), str(unknown)],
            "body": "Bitte Belege nachreichen.",
        },
    )
    assert res.status_code == 200, res.text
    assert [r["ok"] for r in res.json()["results"]] == [True, True, True, False]
    assert sorted(mails) == sorted(ids)
    async with maker() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Comment)
            .where(Comment.application_id.in_(ids), Comment.visibility == "public")
        )
    assert count == 3


async def test_bulk_actions_need_application_manage(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 001700: without ``application.manage`` the routes answer 403."""
    app_id = await _create(maker, seed, 0)
    client = _client(migrated, settings, monkeypatch, _MEMBER)
    body = {"applicationIds": [str(app_id)]}
    assert client.post("/api/bulk/applications/transitions", json=body).status_code == 403
    assert (
        client.post("/api/bulk/applications/comments", json={**body, "body": "x"}).status_code
        == 403
    )
