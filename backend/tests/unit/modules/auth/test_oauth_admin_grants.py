"""Admin view and kill switch for the OAuth grants of every principal.

The tests run without a database. The router uses the FastAPI `TestClient` with
`dependency_overrides` and `FakeSession` from `tests._support.flow_fakes`. `auth` is a
critical module, so every branch of the new router has a test.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.auth import oauth_service
from app.settings import Settings, load_settings
from app.settings import get_settings as get_settings_dep
from tests._support.flow_fakes import fake_session, result

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

SETTINGS = load_settings(
    database_url="postgresql+asyncpg://x/y",
    session_secret="session-secret-0123456",
    magic_link_secret="magic-link-secret-0",
    oidc_issuer="https://kc.example/realms/app",
    oidc_client_id="antrag",
    oidc_client_secret="client-secret-01234",
    oidc_redirect_url="https://antrag.example/api/auth/callback",
    public_base_url="https://antrag.example",
    cookie_secure=False,
)

GRANTS = "/api/admin/oauth-grants"
OWNER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
GRANT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _admin() -> Principal:
    """A user administrator. This is NOT the owner of the listed grants."""
    return Principal(
        sub="admin-1",
        email="admin@example.de",
        roles=["member"],
        permissions={"admin.users"},
    )


def _plain_user() -> Principal:
    return Principal(
        sub="u2", email="u2@example.de", roles=["member"], permissions={"mcp.use"}
    )


def _build_client(
    *,
    db: object | None = None,
    principal: Principal | None = None,
    anonymous: bool = False,
    settings: Settings = SETTINGS,
) -> TestClient:
    app = create_app(settings)
    the_db = db if db is not None else fake_session()

    async def _fake_db() -> AsyncIterator[object]:
        yield the_db

    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_session] = _fake_db
    if not anonymous:
        app.dependency_overrides[get_current_principal] = (
            lambda: principal if principal is not None else _admin()
        )
    return TestClient(app, follow_redirects=False)


def _token_row(
    *,
    grant_id: uuid.UUID = GRANT_ID,
    principal_id: uuid.UUID = OWNER_ID,
    revoked_at: datetime | None = None,
) -> Any:
    return SimpleNamespace(
        id=grant_id,
        principal_id=principal_id,
        client_id="antragsplattform-mcp",
        access_token_hash=b"secret-access-hash",
        refresh_token_hash=b"secret-refresh-hash",
        scope="read votes:write",
        access_ttl_seconds=3600,
        created_at=NOW,
        access_expires_at=NOW + timedelta(hours=1),
        refresh_expires_at=NOW + timedelta(days=30),
        revoked_at=revoked_at,
    )


def _principal_row(
    *,
    row_id: uuid.UUID = OWNER_ID,
    display_name: str | None = "Agent Owner",
    email: str | None = "owner@example.de",
) -> Any:
    return SimpleNamespace(
        id=row_id, sub="owner-1", display_name=display_name, email=email
    )


# --- RBAC ---------------------------------------------------------------------------
def test_list_without_admin_users_is_403_problem_json() -> None:
    client = _build_client(principal=_plain_user())
    resp = client.get(GRANTS)
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["status"] == 403


def test_revoke_without_admin_users_is_403_problem_json() -> None:
    client = _build_client(principal=_plain_user())
    resp = client.delete(f"{GRANTS}/{GRANT_ID}")
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["status"] == 403


def test_list_without_session_is_401_problem_json() -> None:
    client = _build_client(anonymous=True)
    resp = client.get(GRANTS)
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_revoke_without_session_is_401_problem_json() -> None:
    client = _build_client(anonymous=True)
    resp = client.delete(f"{GRANTS}/{GRANT_ID}")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


# --- list ---------------------------------------------------------------------------
def test_admin_lists_grants_of_another_principal() -> None:
    db = fake_session(result((_token_row(), _principal_row())))
    db.scalar_results.append(1)
    client = _build_client(db=db)
    resp = client.get(GRANTS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["limit"] == 50 and body["offset"] == 0
    item = body["items"][0]
    assert item["id"] == str(GRANT_ID)
    assert item["principalName"] == "Agent Owner"
    assert item["principalEmail"] == "owner@example.de"
    assert item["clientId"] == "antragsplattform-mcp"
    assert item["scope"] == "read votes:write"
    assert item["createdAt"].startswith("2026-06-16")
    assert item["accessExpiresAt"] is not None
    assert item["refreshExpiresAt"] is not None


def test_list_never_leaks_a_token_secret_or_a_uuid_as_a_name() -> None:
    db = fake_session(result((_token_row(), _principal_row())))
    db.scalar_results.append(1)
    client = _build_client(db=db)
    resp = client.get(GRANTS)
    raw = resp.text
    # Neither a hash value nor a hash field name reaches the client.
    assert "secret-access-hash" not in raw
    assert "secret-refresh-hash" not in raw
    assert "TokenHash" not in raw and "token_hash" not in raw
    # The name field carries a name, never the principal UUID (see no-uuids-in-ui).
    item = resp.json()["items"][0]
    assert item["principalName"] == "Agent Owner"
    assert item["principalName"] != str(OWNER_ID)


def test_list_falls_back_to_email_then_to_null() -> None:
    db = fake_session(
        result(
            (_token_row(), _principal_row(display_name=None)),
            (
                _token_row(grant_id=OTHER_ID, principal_id=OTHER_ID),
                _principal_row(row_id=OTHER_ID, display_name=None, email=None),
            ),
        )
    )
    db.scalar_results.append(2)
    client = _build_client(db=db)
    items = client.get(GRANTS).json()["items"]
    assert items[0]["principalName"] == "owner@example.de"
    # Neither a display name nor an email: null, never the UUID.
    assert items[1]["principalName"] is None
    assert items[1]["principalEmail"] is None


def test_list_empty_total_none_gives_zero() -> None:
    db = fake_session(result())  # no rows, `scalar` gives None
    client = _build_client(db=db)
    body = client.get(GRANTS).json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_list_filters_by_principal() -> None:
    db = fake_session(result((_token_row(), _principal_row())))
    db.scalar_results.append(1)
    client = _build_client(db=db)
    resp = client.get(GRANTS, params={"principalId": str(OWNER_ID), "limit": 10, "offset": 5})
    assert resp.status_code == 200
    assert resp.json()["limit"] == 10 and resp.json()["offset"] == 5
    # The filter reached the SQL, so the query is scoped to that principal.
    assert "principal_id" in str(db.statements[-1])


def test_list_rejects_an_unknown_query_parameter() -> None:
    client = _build_client()
    resp = client.get(GRANTS, params={"bogus": "1"})
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_list_rejects_a_non_uuid_principal_filter() -> None:
    client = _build_client()
    resp = client.get(GRANTS, params={"principalId": "not-a-uuid"})
    assert resp.status_code == 422


# --- revoke -------------------------------------------------------------------------
def test_revoke_unknown_grant_is_404_problem_json() -> None:
    db = fake_session(result())
    client = _build_client(db=db)
    resp = client.delete(f"{GRANTS}/{GRANT_ID}")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_revoke_foreign_grant_succeeds_and_is_audited() -> None:
    row = _token_row()
    db = fake_session(result(row))
    client = _build_client(db=db)
    resp = client.delete(f"{GRANTS}/{GRANT_ID}")
    assert resp.status_code == 204
    assert row.revoked_at is not None
    assert db.committed == 1
    entry = db.added[0]
    assert entry.action == "role_change"
    assert entry.actor == "admin-1"
    assert entry.target_type == "oauth_token"
    assert entry.target_id == str(GRANT_ID)
    assert entry.data["event"] == "oauth_grant_revoke"
    assert entry.data["principalId"] == str(OWNER_ID)
    assert entry.data["clientId"] == "antragsplattform-mcp"
    assert entry.data["scope"] == "read votes:write"
    # The audit payload carries id references only, never a token secret.
    assert "secret-access-hash" not in str(entry.data)


def test_revoke_already_revoked_grant_is_idempotent() -> None:
    row = _token_row(revoked_at=NOW - timedelta(days=1))
    db = fake_session(result(row))
    client = _build_client(db=db)
    resp = client.delete(f"{GRANTS}/{GRANT_ID}")
    assert resp.status_code == 204
    assert row.revoked_at == NOW - timedelta(days=1)
    assert db.committed == 0
    assert db.added == []


def test_revoke_rejects_a_non_uuid_grant_id() -> None:
    client = _build_client()
    resp = client.delete(f"{GRANTS}/not-a-uuid")
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_revoked_grant_no_longer_authenticates() -> None:
    """The revoke ends the token at once, checked with the runtime resolution path.

    `oauth_service.resolve_access_token` is the function `app.deps` calls for every
    `Bearer apat_…` request. It must reject the row that the admin revoke touched.
    """
    row = _token_row()
    db = fake_session(result(row))
    client = _build_client(db=db)
    assert client.delete(f"{GRANTS}/{GRANT_ID}").status_code == 204

    # Same row, now through the runtime check.
    lookup = fake_session(result(row))
    resolved = await oauth_service.resolve_access_token(
        cast(Any, lookup), token="apat_whatever", now=NOW
    )
    assert resolved is None
