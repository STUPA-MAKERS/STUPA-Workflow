"""Login settings: `GET/PUT /admin/login-settings` and the session renewal on Postgres.

* The defaults are 90 days in a browser tab and 180 days in the installed app.
* The PUT needs `admin.users`, validates the range 1..400 and writes a
  `config_change` audit entry that the audit log cannot revert.
* The renewal locks the session row (`FOR UPDATE SKIP LOCKED`), slides `expires_at`
  with the lifetime of the client, and deletes the session when the IdP refuses.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_principal
from app.modules.audit.models import AuditEntry
from app.modules.auth import oidc
from app.modules.auth.models import AuthSession
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oidc import OidcClaims, OidcError
from app.modules.auth.principal import Principal
from app.modules.auth.session_renewal import renew_principal_session
from app.settings import Settings, load_settings
from tests._support.guest_apps import build_api, guest_settings
from tests.integration.conftest import clear_privacy_tables

pytestmark = pytest.mark.integration

_ADMIN = Principal(sub="users-admin", roles=[], permissions={"admin.users"})
_OTHER = Principal(sub="site-admin", roles=[], permissions={"admin.site"})


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    clear_privacy_tables(engine)
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()
    clear_privacy_tables(engine)


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


async def test_defaults_update_and_audit(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(migrated, settings, monkeypatch, _ADMIN) as client:
        got = client.get("/api/admin/login-settings")
        assert got.status_code == 200, got.text
        assert got.json()["webSessionDays"] == 90
        assert got.json()["pwaSessionDays"] == 180
        put = client.put(
            "/api/admin/login-settings", json={"webSessionDays": 30, "pwaSessionDays": 365}
        )
        assert put.status_code == 200, put.text
        assert put.json()["webSessionDays"] == 30
        assert put.json()["pwaSessionDays"] == 365
        assert put.json()["updatedBy"] == "users-admin"
        assert client.get("/api/admin/login-settings").json()["pwaSessionDays"] == 365

    async with maker() as session:
        entry = (
            await session.scalars(
                select(AuditEntry).where(
                    AuditEntry.action == "config_change",
                    AuditEntry.target_type == "login_settings",
                )
            )
        ).one()
    assert entry.data == {
        "webSessionDays": {"from": 90, "to": 30},
        "pwaSessionDays": {"from": 180, "to": 365},
    }


@pytest.mark.parametrize(
    "body",
    [
        {"webSessionDays": 0, "pwaSessionDays": 180},
        {"webSessionDays": 90, "pwaSessionDays": 401},
        {"webSessionDays": 90},
        {"webSessionDays": 90, "pwaSessionDays": 180, "extra": 1},
    ],
)
async def test_put_rejects_bad_values(
    migrated: tuple[str, str],
    engine: Engine,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object],
) -> None:
    with _client(migrated, settings, monkeypatch, _ADMIN) as client:
        resp = client.put("/api/admin/login-settings", json=body)
    assert resp.status_code == 422, resp.text


async def test_routes_need_admin_users(
    migrated: tuple[str, str],
    engine: Engine,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(migrated, settings, monkeypatch, _OTHER) as client:
        assert client.get("/api/admin/login-settings").status_code == 403
        put = client.put(
            "/api/admin/login-settings", json={"webSessionDays": 1, "pwaSessionDays": 1}
        )
        assert put.status_code == 403
    with _client(migrated, settings, monkeypatch, None) as client:
        assert client.get("/api/admin/login-settings").status_code == 401


def _oidc_settings(db_url: str) -> Settings:
    return load_settings(
        database_url=db_url,
        session_secret="session-secret-0123",
        magic_link_secret="magic-link-secret-0",
        oidc_issuer="https://sso.example/",
        oidc_client_id="antrag",
        oidc_client_secret="client-secret-01234",
        oidc_redirect_url="https://antrag.example/api/auth/callback",
    )


async def _seed_session(
    maker: async_sessionmaker[AsyncSession], *, client: str
) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as session:
        row = PrincipalRow(sub=f"renew-{uuid.uuid4()}", oidc_groups=["old"])
        session.add(row)
        await session.flush()
        auth = AuthSession(
            sid=f"sid-{uuid.uuid4()}",
            principal_id=row.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            refresh_token="rt1",
            client=client,
            revalidated_at=datetime.now(UTC) - timedelta(hours=13),
        )
        session.add(auth)
        await session.commit()
        return row.id, auth.id


async def test_renewal_slides_and_refreshes_groups(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id, session_id = await _seed_session(maker, client="pwa")

    async def _refresh(_s: Settings, *, refresh_token: str) -> dict[str, str]:
        return {"id_token": "idt2", "refresh_token": "rt2"}

    async def _verify(_s: Settings, *, id_token: str, sub: str) -> OidcClaims:
        return OidcClaims(sub=sub, email=None, name="N", groups=["new"])

    monkeypatch.setattr(oidc, "refresh_tokens", _refresh)
    monkeypatch.setattr(oidc, "verify_refreshed_id_token", _verify)
    now = datetime.now(UTC)
    async with maker() as session:
        auth = await session.get(AuthSession, session_id)
        row = await session.get(PrincipalRow, principal_id)
        assert auth is not None and row is not None
        ok = await renew_principal_session(
            session, _oidc_settings(migrated[1]), session=auth, principal=row, now=now
        )
    assert ok
    async with maker() as session:
        auth = await session.get(AuthSession, session_id)
        row = await session.get(PrincipalRow, principal_id)
        assert auth is not None and row is not None
        assert auth.refresh_token == "rt2"
        assert auth.revalidated_at == now
        assert auth.expires_at == now + timedelta(days=180)
        assert row.oidc_groups == ["new"]


async def test_renewal_refused_deletes_the_session(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id, session_id = await _seed_session(maker, client="web")

    async def _refused(_s: Settings, *, refresh_token: str) -> dict[str, str]:
        raise OidcError("invalid_grant")

    monkeypatch.setattr(oidc, "refresh_tokens", _refused)
    async with maker() as session:
        auth = await session.get(AuthSession, session_id)
        row = await session.get(PrincipalRow, principal_id)
        assert auth is not None and row is not None
        ok = await renew_principal_session(
            session,
            _oidc_settings(migrated[1]),
            session=auth,
            principal=row,
            now=datetime.now(UTC),
        )
    assert not ok
    async with maker() as session:
        assert await session.get(AuthSession, session_id) is None
