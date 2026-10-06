"""Guest application settings: `GET/PUT /admin/guest-settings` and the public TTL (Z1).

* The defaults are 12 hours to confirm and links without an expiry.
* The PUT needs `admin.deadlines`, validates the ranges and writes a `config_change`
  audit entry that the audit log cannot revert.
* `GET /site-config` returns `confirmTtlHours`, `linkTtlDays` and the upload limits.
* A new magic link gets `link_ttl_days`. NULL gives a link without an expiry.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_principal
from app.modules.applications.models import MagicLink
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.settings import Settings
from tests._support.guest_apps import (
    build_api,
    create_guest_application,
    guest_settings,
    issue_magic_token,
    seed_guest_flow,
)

pytestmark = pytest.mark.integration

_ADMIN = Principal(sub="deadline-admin", roles=[], permissions={"admin.deadlines"})
_OTHER = Principal(sub="site-admin", roles=[], permissions={"admin.site"})


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


def _client(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    principal: Principal | None,
) -> TestClient:
    api = build_api(migrated[1], settings, monkeypatch)
    api.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(api)


async def test_defaults_update_audit_and_public_ttl(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(migrated, settings, monkeypatch, _ADMIN) as client:
        got = client.get("/api/admin/guest-settings")
        assert got.status_code == 200, got.text
        assert got.json()["confirmTtlHours"] == 12
        assert got.json()["linkTtlDays"] is None
        public = client.get("/api/site-config").json()
        assert public["confirmTtlHours"] == 12
        assert public["linkTtlDays"] is None
        assert public["attachmentLimits"]["maxDraftFiles"] == 20

        put = client.put(
            "/api/admin/guest-settings", json={"confirmTtlHours": 48, "linkTtlDays": 30}
        )
        assert put.status_code == 200, put.text
        body = put.json()
        assert body["confirmTtlHours"] == 48
        assert body["linkTtlDays"] == 30
        assert body["updatedBy"] == "deadline-admin"
        assert body["updatedAt"] is not None

        public = client.get("/api/site-config").json()
        assert public["confirmTtlHours"] == 48
        assert public["linkTtlDays"] == 30
        assert client.get("/api/admin/guest-settings").json()["linkTtlDays"] == 30

    # The audit entry holds the change. It has no revision, so it is not revertable.
    async with maker() as session:
        entry = (
            await session.scalars(
                select(AuditEntry).where(
                    AuditEntry.action == "config_change",
                    AuditEntry.target_type == "guest_application_settings",
                )
            )
        ).one()
    assert entry.actor == "deadline-admin"
    assert entry.data == {
        "confirmTtlHours": {"from": 12, "to": 48},
        "linkTtlDays": {"from": None, "to": 30},
    }
    assert "revisionId" not in entry.data


async def test_link_lifetime_follows_the_setting(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_guest_flow(maker)
    app_id = await create_guest_application(maker, seed)

    await issue_magic_token(maker, settings, app_id)
    with _client(migrated, settings, monkeypatch, _ADMIN) as client:
        put = client.put(
            "/api/admin/guest-settings", json={"confirmTtlHours": 12, "linkTtlDays": 7}
        )
        assert put.status_code == 200, put.text
    before = datetime.now(UTC)
    await issue_magic_token(maker, settings, app_id)

    async with maker() as session:
        links = (
            await session.scalars(
                select(MagicLink)
                .where(MagicLink.application_id == app_id)
                .order_by(MagicLink.created_at)
            )
        ).all()
    unlimited, limited = links
    assert unlimited.scope == "edit" and unlimited.expires_at is None
    assert limited.scope == "edit" and limited.single_use is False
    assert limited.expires_at is not None
    assert before + timedelta(days=7) - timedelta(minutes=1) < limited.expires_at
    assert limited.expires_at < before + timedelta(days=7, minutes=1)


@pytest.mark.parametrize(
    "body",
    [
        {"confirmTtlHours": 0, "linkTtlDays": None},
        {"confirmTtlHours": 721, "linkTtlDays": None},
        {"confirmTtlHours": 12, "linkTtlDays": 0},
        {"confirmTtlHours": 12, "linkTtlDays": 3651},
        {"confirmTtlHours": 12},
        {"confirmTtlHours": 12, "linkTtlDays": None, "other": 1},
    ],
)
async def test_put_rejects_invalid_values(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object],
) -> None:
    with _client(migrated, settings, monkeypatch, _ADMIN) as client:
        resp = client.put("/api/admin/guest-settings", json=body)
    assert resp.status_code == 422, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_routes_need_admin_deadlines(
    migrated: tuple[str, str],
    engine: Engine,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(migrated, settings, monkeypatch, _OTHER) as client:
        assert client.get("/api/admin/guest-settings").status_code == 403
        put = client.put(
            "/api/admin/guest-settings", json={"confirmTtlHours": 5, "linkTtlDays": None}
        )
        assert put.status_code == 403
    with _client(migrated, settings, monkeypatch, None) as client:
        assert client.get("/api/admin/guest-settings").status_code == 401
        # The public site config needs no login.
        public = client.get("/api/site-config").json()
        assert public["confirmTtlHours"] == 12
        assert public["linkTtlDays"] is None
        assert public["attachmentLimits"]["maxDraftFiles"] == 20
