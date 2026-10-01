"""F23 and F12: a logged-in submission for another email stays unconfirmed (real Postgres).

Before F23 a logged-in person could enter any address, and the application counted
as confirmed at once. Now only the account email (compared without case) confirms
the submission. Any other address gets `email_confirmed_at = NULL` and a magic link,
and the application rests in the flow like a guest submission (P3b).

Every create writes an `application_create` audit entry without PII (F12).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_principal
from app.modules.applications.models import Application
from app.modules.applications.router import get_magic_link_sender
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.settings import Settings
from tests._support.guest_apps import (
    GuestSeed,
    build_api,
    guest_settings,
    issue_magic_token,
    redeem,
    seed_guest_flow,
)

pytestmark = pytest.mark.integration

_MEMBER = Principal(
    sub="member-sub", roles=["member"], email="Member@Example.org", display_name="M"
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


def _submit(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    seed: GuestSeed,
    principal: Principal | None,
    email: str | None,
) -> tuple[uuid.UUID, list[tuple[str, uuid.UUID]]]:
    sent: list[tuple[str, uuid.UUID]] = []

    async def _sender(_settings: Settings, to: str, app_id: uuid.UUID, _pool: Any) -> None:
        sent.append((to, app_id))

    api = build_api(migrated[1], settings, monkeypatch)
    api.dependency_overrides[get_current_principal] = lambda: principal
    api.dependency_overrides[get_magic_link_sender] = lambda: _sender
    body: dict[str, Any] = {"typeId": str(seed.type_id), "data": {"title": "Antrag"}}
    if email is not None:
        body["applicantEmail"] = email
    with TestClient(api) as client:
        resp = client.post("/api/applications", json=body)
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["applicationId"]), sent


async def _get(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID) -> Application:
    async with maker() as session:
        app = await session.get(Application, app_id)
        assert app is not None
        return app


async def _create_audit(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID) -> AuditEntry:
    async with maker() as session:
        return (
            await session.scalars(
                select(AuditEntry).where(
                    AuditEntry.action == "application_create",
                    AuditEntry.target_id == str(app_id),
                )
            )
        ).one()


async def test_foreign_email_stays_unconfirmed_until_the_link(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_guest_flow(maker)
    app_id, sent = _submit(
        migrated, settings, monkeypatch, seed, _MEMBER, "someone-else@example.org"
    )
    app = await _get(maker, app_id)
    assert app.email_confirmed_at is None
    assert app.created_by == "member-sub"
    assert sent == [("someone-else@example.org", app_id)]

    entry = await _create_audit(maker, app_id)
    assert entry.actor == "member-sub"
    assert entry.target_type == "application"
    assert entry.data == {
        "typeId": str(seed.type_id),
        "gremiumId": str(seed.gremium_id),
        "initialStateId": str(seed.open_state_id),
        "emailConfirmed": False,
    }

    # The owner of the address confirms it through the link.
    token = await issue_magic_token(maker, settings, app_id, "someone-else@example.org")
    assert await redeem(maker, settings, token) == "edit"
    assert (await _get(maker, app_id)).email_confirmed_at is not None


async def test_account_email_confirms_at_once_without_case(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_guest_flow(maker)
    app_id, sent = _submit(migrated, settings, monkeypatch, seed, _MEMBER, "member@EXAMPLE.org")
    assert (await _get(maker, app_id)).email_confirmed_at is not None
    assert len(sent) == 1
    assert (await _create_audit(maker, app_id)).data["emailConfirmed"] is True


async def test_missing_email_takes_the_account_email(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_guest_flow(maker)
    app_id, sent = _submit(migrated, settings, monkeypatch, seed, _MEMBER, None)
    assert (await _get(maker, app_id)).email_confirmed_at is not None
    assert sent == [("Member@Example.org", app_id)]


async def test_account_without_email_cannot_confirm(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_guest_flow(maker)
    no_mail = Principal(sub="no-mail", roles=["member"], email=None)
    app_id, _ = _submit(migrated, settings, monkeypatch, seed, no_mail, "member@example.org")
    assert (await _get(maker, app_id)).email_confirmed_at is None
