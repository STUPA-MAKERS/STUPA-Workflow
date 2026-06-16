"""Vollabdeckung (Line + Branch) der Auth-/OAuth-Endpunkte und -Services (#MCP).

DB-frei: Router via FastAPI-``TestClient`` + ``dependency_overrides``, Services via
``FakeSession`` (``tests._support.flow_fakes``). Deckt gezielt jeden Fehler-/Guard-Zweig
ab (kritisches Modul: 100 % Branch ist CI-Gate).
"""

from __future__ import annotations

import base64
import hashlib
import tarfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.auth import mcp_router as mcp_router_mod
from app.modules.auth import oauth, oauth_service, rbac, service, sessions
from app.modules.auth import oauth_router as oauth_router_mod
from app.modules.auth import router as router_mod
from app.modules.auth.models import GroupMapping, RoleAssignment
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oidc import OidcClaims
from app.settings import Settings, get_settings, load_settings
from app.shared.errors import ForbiddenError
from tests._support.flow_fakes import fake_session, result

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

ENABLED = load_settings(
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
DISABLED = load_settings(
    database_url="postgresql+asyncpg://x/y",
    session_secret="session-secret-0123456",
    magic_link_secret="magic-link-secret-0",
    public_base_url="https://antrag.example",
)

CLIENT_ID = ENABLED.oauth_mcp_client_id
LOOPBACK = "http://127.0.0.1:7777/cb"


def _challenge(verifier: str) -> str:
    d = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode("ascii")


def _mcp_principal() -> Principal:
    return Principal(
        sub="u1",
        email="e@x.de",
        roles=["member"],
        permissions={"mcp.use", "application.read", "vote.manage"},
    )


def _build_client(
    settings: Settings,
    *,
    db: object | None = None,
    principal: Principal | None = None,
    no_principal_override: bool = False,
) -> TestClient:
    app = create_app(settings)
    the_db = db if db is not None else fake_session()

    async def _fake_db() -> AsyncIterator[object]:
        yield the_db

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = _fake_db
    if not no_principal_override:
        app.dependency_overrides[get_current_principal] = (
            lambda: principal if principal is not None else _mcp_principal()
        )
    return TestClient(app, follow_redirects=False)


# =========================================================================== #
# oauth_router.authorize
# =========================================================================== #
def test_authorize_oidc_disabled_404() -> None:
    client = _build_client(DISABLED)
    resp = client.get(
        "/api/oauth/authorize",
        params={"response_type": "code", "client_id": CLIENT_ID,
                "redirect_uri": LOOPBACK, "code_challenge": "x",
                "code_challenge_method": "S256"},
    )
    assert resp.status_code == 404


def test_authorize_unknown_client_400() -> None:
    client = _build_client(ENABLED)
    resp = client.get("/api/oauth/authorize", params={"client_id": "wrong"})
    assert resp.status_code == 400


def test_authorize_non_loopback_redirect_400() -> None:
    client = _build_client(ENABLED)
    resp = client.get(
        "/api/oauth/authorize",
        params={"client_id": CLIENT_ID, "redirect_uri": "https://evil.example/cb"},
    )
    assert resp.status_code == 400


def test_authorize_bad_response_type_redirects_error() -> None:
    client = _build_client(ENABLED)
    resp = client.get(
        "/api/oauth/authorize",
        params={"response_type": "token", "client_id": CLIENT_ID,
                "redirect_uri": LOOPBACK, "state": "s1"},
    )
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert "error=unsupported_response_type" in loc
    assert "state=s1" in loc


def test_authorize_missing_pkce_challenge_redirects_error() -> None:
    client = _build_client(ENABLED)
    resp = client.get(
        "/api/oauth/authorize",
        params={"response_type": "code", "client_id": CLIENT_ID,
                "redirect_uri": LOOPBACK, "code_challenge_method": "S256",
                "code_challenge": ""},
    )
    assert resp.status_code == 302
    assert "error=invalid_request" in resp.headers["location"]


def test_authorize_wrong_pkce_method_redirects_error() -> None:
    client = _build_client(ENABLED)
    resp = client.get(
        "/api/oauth/authorize",
        params={"response_type": "code", "client_id": CLIENT_ID,
                "redirect_uri": LOOPBACK, "code_challenge_method": "plain",
                "code_challenge": "abc"},
    )
    assert resp.status_code == 302
    assert "error=invalid_request" in resp.headers["location"]


def test_authorize_invalid_scope_redirects_error() -> None:
    client = _build_client(ENABLED)
    resp = client.get(
        "/api/oauth/authorize",
        params={"response_type": "code", "client_id": CLIENT_ID,
                "redirect_uri": LOOPBACK, "code_challenge_method": "S256",
                "code_challenge": "abc", "scope": "bogus:scope"},
    )
    assert resp.status_code == 302
    assert "error=invalid_scope" in resp.headers["location"]


def test_authorize_success_starts_oidc_login() -> None:
    client = _build_client(ENABLED)
    resp = client.get(
        "/api/oauth/authorize",
        params={"response_type": "code", "client_id": CLIENT_ID,
                "redirect_uri": LOOPBACK, "code_challenge_method": "S256",
                "code_challenge": "abc", "scope": "read"},
    )
    assert resp.status_code == 307
    assert resp.headers["location"].endswith("/api/auth/login")
    assert ENABLED.oauth_tx_cookie_name in resp.headers.get("set-cookie", "")


def test_authorize_redirect_error_appends_with_query_sep() -> None:
    """redirect_uri mit vorhandenem Query → ``&``-Separator-Zweig."""
    client = _build_client(ENABLED)
    resp = client.get(
        "/api/oauth/authorize",
        params={"response_type": "token", "client_id": CLIENT_ID,
                "redirect_uri": "http://localhost:9/cb?foo=1"},
    )
    assert resp.status_code == 302
    assert "?foo=1&error=" in resp.headers["location"]


def test_authorize_redirect_error_without_state() -> None:
    """state leer → kein ``state``-Param im Fehler-Redirect."""
    client = _build_client(ENABLED)
    resp = client.get(
        "/api/oauth/authorize",
        params={"response_type": "token", "client_id": CLIENT_ID,
                "redirect_uri": LOOPBACK},
    )
    assert "state=" not in resp.headers["location"]


def test_is_loopback_redirect_value_error() -> None:
    """Unparsbare URL (kaputte IPv6-Klammer) → ValueError-Zweig → False."""
    assert oauth_router_mod._is_loopback_redirect("http://[::1") is False


def test_is_loopback_redirect_non_loopback_host() -> None:
    assert oauth_router_mod._is_loopback_redirect("http://example.com/cb") is False
    assert oauth_router_mod._is_loopback_redirect("https://localhost/cb") is False
    assert oauth_router_mod._is_loopback_redirect("http://localhost/cb") is True
    # IPv6-Loopback mit Klammern.
    assert oauth_router_mod._is_loopback_redirect("http://[::1]/cb") is True


# =========================================================================== #
# oauth_router.finish
# =========================================================================== #
def test_finish_unauthenticated_401() -> None:
    client = _build_client(ENABLED, no_principal_override=True)
    assert client.get("/api/oauth/finish").status_code == 401


def test_finish_missing_tx_400() -> None:
    client = _build_client(ENABLED)
    assert client.get("/api/oauth/finish").status_code == 400


def test_finish_invalid_tx_cookie_400() -> None:
    client = _build_client(ENABLED)
    client.cookies.set(ENABLED.oauth_tx_cookie_name, "garbage")
    assert client.get("/api/oauth/finish").status_code == 400


def test_finish_valid_tx_redirects_to_consent() -> None:
    client = _build_client(ENABLED)
    tx = sessions.issue_oauth_tx(
        ENABLED.session_secret,
        {"client_id": CLIENT_ID, "redirect_uri": LOOPBACK,
         "code_challenge": "abc", "scope": "read", "state": "s1"},
    )
    client.cookies.set(ENABLED.oauth_tx_cookie_name, tx)
    resp = client.get("/api/oauth/finish")
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/oauth/consent")


# =========================================================================== #
# oauth_router.token
# =========================================================================== #
def test_token_oidc_disabled_404() -> None:
    client = _build_client(DISABLED)
    resp = client.post("/api/oauth/token", data={"grant_type": "authorization_code"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "invalid_request"


def test_token_unknown_client_401() -> None:
    client = _build_client(ENABLED)
    resp = client.post(
        "/api/oauth/token", data={"grant_type": "authorization_code", "client_id": "x"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_client"


def test_token_unsupported_grant_400() -> None:
    client = _build_client(ENABLED)
    resp = client.post(
        "/api/oauth/token", data={"grant_type": "weird", "client_id": CLIENT_ID}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "unsupported_grant_type"


def test_token_authorization_code_success(monkeypatch: pytest.MonkeyPatch) -> None:
    issued = oauth_service.IssuedTokens("apat_a", "aprt_r", "read", 3600)

    async def _exchange(db: object, **kw: object) -> oauth_service.IssuedTokens:
        return issued

    monkeypatch.setattr(oauth_router_mod.oauth_service, "exchange_code", _exchange)
    db = fake_session()
    client = _build_client(ENABLED, db=db)
    resp = client.post(
        "/api/oauth/token",
        data={"grant_type": "authorization_code", "client_id": CLIENT_ID,
              "code": "c", "code_verifier": "v", "redirect_uri": LOOPBACK},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "apat_a"
    assert body["token_type"] == "Bearer"
    assert body["refresh_token"] == "aprt_r"
    assert body["scope"] == "read"
    assert db.committed == 1


def test_token_refresh_success(monkeypatch: pytest.MonkeyPatch) -> None:
    issued = oauth_service.IssuedTokens("apat_b", "aprt_s", "read", None)

    async def _refresh(db: object, **kw: object) -> oauth_service.IssuedTokens:
        return issued

    monkeypatch.setattr(oauth_router_mod.oauth_service, "refresh_tokens", _refresh)
    client = _build_client(ENABLED)
    resp = client.post(
        "/api/oauth/token",
        data={"grant_type": "refresh_token", "client_id": CLIENT_ID,
              "refresh_token": "aprt_old"},
    )
    assert resp.status_code == 200
    assert resp.json()["expires_in"] is None


def test_token_oauth_error_maps_to_body(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _exchange(db: object, **kw: object) -> oauth_service.IssuedTokens:
        raise oauth.OAuthError("invalid_grant", "code expired")

    monkeypatch.setattr(oauth_router_mod.oauth_service, "exchange_code", _exchange)
    client = _build_client(ENABLED)
    resp = client.post(
        "/api/oauth/token",
        data={"grant_type": "authorization_code", "client_id": CLIENT_ID},
    )
    assert resp.status_code == 400
    assert resp.json() == {"error": "invalid_grant", "error_description": "code expired"}


# =========================================================================== #
# oauth_router.consent_request
# =========================================================================== #
def _issue_tx(scope: str = "read votes:write", state: str = "s1") -> str:
    return sessions.issue_oauth_tx(
        ENABLED.session_secret,
        {"client_id": CLIENT_ID, "redirect_uri": LOOPBACK,
         "code_challenge": "abc", "scope": scope, "state": state},
    )


def test_consent_request_no_cookie_400() -> None:
    client = _build_client(ENABLED)
    assert client.get("/api/oauth/consent-request").status_code == 400


def test_consent_request_invalid_tx_400() -> None:
    client = _build_client(ENABLED)
    client.cookies.set(ENABLED.oauth_tx_cookie_name, "bad")
    assert client.get("/api/oauth/consent-request").status_code == 400


def test_consent_request_marks_held_scopes() -> None:
    client = _build_client(ENABLED, principal=_mcp_principal())
    client.cookies.set(ENABLED.oauth_tx_cookie_name, _issue_tx())
    body = client.get("/api/oauth/consent-request").json()
    assert body["clientId"] == CLIENT_ID
    assert body["canUseMcp"] is True
    scopes = {s["key"]: s["held"] for s in body["requestedScopes"]}
    # read → application.read (held); votes:write → vote.manage (held).
    assert scopes["read"] is True
    assert scopes["votes:write"] is True
    assert body["defaultLifetime"] == oauth.DEFAULT_LIFETIME
    assert body["lifetimes"] == list(oauth.LIFETIMES.keys())


def test_consent_request_unheld_scope() -> None:
    # Principal ohne admin-Rechte → admin:write nicht "held".
    p = Principal(sub="u", permissions={"mcp.use"})
    client = _build_client(ENABLED, principal=p)
    client.cookies.set(ENABLED.oauth_tx_cookie_name, _issue_tx(scope="admin:write"))
    body = client.get("/api/oauth/consent-request").json()
    held = {s["key"]: s["held"] for s in body["requestedScopes"]}
    assert held["admin:write"] is False


# =========================================================================== #
# oauth_router.consent
# =========================================================================== #
def test_consent_no_tx_400() -> None:
    client = _build_client(ENABLED)
    resp = client.post("/api/oauth/consent", json={"approve": True, "scopes": ["read"]})
    assert resp.status_code == 400


def test_consent_deny_returns_access_denied_redirect() -> None:
    client = _build_client(ENABLED)
    client.cookies.set(ENABLED.oauth_tx_cookie_name, _issue_tx())
    resp = client.post("/api/oauth/consent", json={"approve": False})
    assert resp.status_code == 200
    assert "error=access_denied" in resp.json()["redirect"]
    assert "state=s1" in resp.json()["redirect"]
    # tx-Cookie wird gelöscht.
    assert "ap_oauth_tx=" in resp.headers.get("set-cookie", "")


def test_consent_deny_without_state() -> None:
    client = _build_client(ENABLED)
    client.cookies.set(ENABLED.oauth_tx_cookie_name, _issue_tx(state=""))
    resp = client.post("/api/oauth/consent", json={"approve": False})
    assert "state=" not in resp.json()["redirect"]


def test_consent_approve_missing_mcp_use_403() -> None:
    p = Principal(sub="u", permissions={"application.read"})  # kein mcp.use
    client = _build_client(ENABLED, principal=p)
    client.cookies.set(ENABLED.oauth_tx_cookie_name, _issue_tx())
    resp = client.post("/api/oauth/consent", json={"approve": True, "scopes": ["read"]})
    assert resp.status_code == 403


def test_consent_approve_no_valid_scopes_400() -> None:
    client = _build_client(ENABLED, principal=_mcp_principal())
    client.cookies.set(ENABLED.oauth_tx_cookie_name, _issue_tx(scope="read"))
    # angefragt war nur "read"; gewählt "budget:write" (nicht angefragt) → leer → 400.
    resp = client.post(
        "/api/oauth/consent", json={"approve": True, "scopes": ["budget:write"]}
    )
    assert resp.status_code == 400


def test_consent_approve_principal_not_found_400() -> None:
    db = fake_session(result())  # _principal_row_id → None
    client = _build_client(ENABLED, db=db, principal=_mcp_principal())
    client.cookies.set(ENABLED.oauth_tx_cookie_name, _issue_tx(scope="read"))
    resp = client.post(
        "/api/oauth/consent", json={"approve": True, "scopes": ["read"]}
    )
    assert resp.status_code == 400


def test_consent_approve_success_mints_code(monkeypatch: pytest.MonkeyPatch) -> None:
    db = fake_session(result("pid-row"))  # _principal_row_id → pid

    async def _create(db: object, **kw: object) -> str:
        assert kw["scope"] == "read"
        return "apac_thecode"

    monkeypatch.setattr(
        oauth_router_mod.oauth_service, "create_authorization_code", _create
    )
    client = _build_client(ENABLED, db=db, principal=_mcp_principal())
    client.cookies.set(ENABLED.oauth_tx_cookie_name, _issue_tx(scope="read"))
    resp = client.post(
        "/api/oauth/consent",
        json={"approve": True, "scopes": ["read"], "lifetime": "1h"},
    )
    assert resp.status_code == 200
    assert "code=apac_thecode" in resp.json()["redirect"]
    assert "state=s1" in resp.json()["redirect"]
    assert db.committed == 1


def test_consent_approve_success_without_state(monkeypatch: pytest.MonkeyPatch) -> None:
    db = fake_session(result("pid-row"))

    async def _create(db: object, **kw: object) -> str:
        return "apac_x"

    monkeypatch.setattr(
        oauth_router_mod.oauth_service, "create_authorization_code", _create
    )
    client = _build_client(ENABLED, db=db, principal=_mcp_principal())
    client.cookies.set(ENABLED.oauth_tx_cookie_name, _issue_tx(scope="read", state=""))
    resp = client.post(
        "/api/oauth/consent", json={"approve": True, "scopes": ["read"]}
    )
    assert "state=" not in resp.json()["redirect"]


# =========================================================================== #
# oauth_router.list_grants / revoke
# =========================================================================== #
def test_list_grants_no_principal_row_empty() -> None:
    db = fake_session(result())  # _principal_row_id → None
    client = _build_client(ENABLED, db=db)
    assert client.get("/api/oauth/grants").json() == []


def test_list_grants_returns_rows() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    row_full = SimpleNamespace(
        id="g1", client_id=CLIENT_ID, scope="read", created_at=created,
        access_expires_at=created + timedelta(hours=1),
        refresh_expires_at=created + timedelta(days=30),
    )
    row_never = SimpleNamespace(
        id="g2", client_id=CLIENT_ID, scope="read", created_at=None,
        access_expires_at=None, refresh_expires_at=None,
    )
    db = fake_session(result("pid"), result(row_full, row_never))
    client = _build_client(ENABLED, db=db)
    body = client.get("/api/oauth/grants").json()
    assert body[0]["id"] == "g1"
    assert body[0]["accessExpiresAt"] is not None
    assert body[0]["refreshExpiresAt"] is not None
    assert body[0]["createdAt"] is not None
    # never-expire + kein created_at → None.
    assert body[1]["createdAt"] is None
    assert body[1]["accessExpiresAt"] is None
    assert body[1]["refreshExpiresAt"] is None


def test_revoke_grant_not_found_when_missing() -> None:
    db = fake_session(result("pid"), result())  # pid found, row None
    client = _build_client(ENABLED, db=db)
    assert client.delete("/api/oauth/grants/gx").status_code == 404


def test_revoke_grant_not_found_when_foreign() -> None:
    foreign = SimpleNamespace(id="gx", principal_id="other-pid", revoked_at=None)
    db = fake_session(result("pid"), result(foreign))
    client = _build_client(ENABLED, db=db)
    assert client.delete("/api/oauth/grants/gx").status_code == 404


def test_revoke_grant_not_found_when_no_pid() -> None:
    own = SimpleNamespace(id="gx", principal_id="pid", revoked_at=None)
    # pid None but row exists → pid is None branch → 404.
    db = fake_session(result(), result(own))
    client = _build_client(ENABLED, db=db)
    assert client.delete("/api/oauth/grants/gx").status_code == 404


def test_revoke_grant_success() -> None:
    own = SimpleNamespace(id="gx", principal_id="pid", revoked_at=None)
    db = fake_session(result("pid"), result(own))
    client = _build_client(ENABLED, db=db)
    resp = client.delete("/api/oauth/grants/gx")
    assert resp.status_code == 204
    assert own.revoked_at is not None
    assert db.committed == 1


def test_revoke_grant_already_revoked_no_commit() -> None:
    already = SimpleNamespace(
        id="gx", principal_id="pid", revoked_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    db = fake_session(result("pid"), result(already))
    client = _build_client(ENABLED, db=db)
    resp = client.delete("/api/oauth/grants/gx")
    assert resp.status_code == 204
    assert db.committed == 0  # schon widerrufen → kein Commit


def test_revoke_all_grants_no_pid_noop() -> None:
    db = fake_session(result())  # _principal_row_id → None
    client = _build_client(ENABLED, db=db)
    assert client.delete("/api/oauth/grants").status_code == 204
    assert db.committed == 0


def test_revoke_all_grants_marks_rows() -> None:
    r1 = SimpleNamespace(revoked_at=None)
    r2 = SimpleNamespace(revoked_at=None)
    db = fake_session(result("pid"), result(r1, r2))
    client = _build_client(ENABLED, db=db)
    assert client.delete("/api/oauth/grants").status_code == 204
    assert r1.revoked_at is not None and r2.revoked_at is not None
    assert db.committed == 1


# =========================================================================== #
# oauth_router well-known metadata
# =========================================================================== #
def test_authorization_server_metadata() -> None:
    client = _build_client(ENABLED)
    body = client.get("/.well-known/oauth-authorization-server").json()
    assert body["issuer"] == "https://antrag.example"
    assert body["authorization_endpoint"].endswith("/api/oauth/authorize")
    assert body["token_endpoint"].endswith("/api/oauth/token")
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["scopes_supported"] == sorted(oauth.SCOPES.keys())


def test_protected_resource_metadata() -> None:
    client = _build_client(ENABLED)
    body = client.get("/.well-known/oauth-protected-resource").json()
    assert body["resource"] == "https://antrag.example/api"
    assert body["authorization_servers"] == ["https://antrag.example"]
    assert body["scopes_supported"] == sorted(oauth.SCOPES.keys())


# =========================================================================== #
# oauth_service
# =========================================================================== #
async def test_create_authorization_code_persists_and_returns_clear() -> None:
    db = fake_session()
    code = await oauth_service.create_authorization_code(
        db, principal_id=cast(Any, "pid"), client_id=CLIENT_ID, redirect_uri=LOOPBACK,
        code_challenge="ch", scope="read", now=NOW, ttl_seconds=300,
        access_ttl_seconds=3600,
    )
    assert code.startswith("apac_")
    assert len(db.added) == 1
    assert db.flushed == 1
    # Hash der DB-Zeile stimmt mit dem ausgegebenen Code überein.
    assert db.added[0].code_hash == oauth.hash_token(code)


async def test_exchange_code_not_found() -> None:
    db = fake_session(result())
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.exchange_code(
            db, code="c", code_verifier="v", redirect_uri=LOOPBACK,
            client_id=CLIENT_ID, now=NOW, access_ttl=3600, refresh_ttl=86400,
        )
    assert exc.value.error == "invalid_grant"
    assert "invalid or already used" in exc.value.description


async def test_exchange_code_expired() -> None:
    row = SimpleNamespace(used_at=None, expires_at=NOW - timedelta(seconds=1))
    db = fake_session(result(row))
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.exchange_code(
            db, code="c", code_verifier="v", redirect_uri=LOOPBACK,
            client_id=CLIENT_ID, now=NOW, access_ttl=3600, refresh_ttl=86400,
        )
    assert "expired" in exc.value.description


async def test_exchange_code_already_used() -> None:
    row = SimpleNamespace(used_at=NOW, expires_at=NOW + timedelta(hours=1))
    db = fake_session(result(row))
    with pytest.raises(oauth.OAuthError):
        await oauth_service.exchange_code(
            db, code="c", code_verifier="v", redirect_uri=LOOPBACK,
            client_id=CLIENT_ID, now=NOW, access_ttl=3600, refresh_ttl=86400,
        )


async def test_exchange_code_client_mismatch() -> None:
    row = SimpleNamespace(
        used_at=None, expires_at=NOW + timedelta(hours=1),
        client_id="other", redirect_uri=LOOPBACK,
    )
    db = fake_session(result(row))
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.exchange_code(
            db, code="c", code_verifier="v", redirect_uri=LOOPBACK,
            client_id=CLIENT_ID, now=NOW, access_ttl=3600, refresh_ttl=86400,
        )
    assert "mismatch" in exc.value.description


async def test_exchange_code_redirect_mismatch() -> None:
    row = SimpleNamespace(
        used_at=None, expires_at=NOW + timedelta(hours=1),
        client_id=CLIENT_ID, redirect_uri="http://127.0.0.1:1/other",
    )
    db = fake_session(result(row))
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.exchange_code(
            db, code="c", code_verifier="v", redirect_uri=LOOPBACK,
            client_id=CLIENT_ID, now=NOW, access_ttl=3600, refresh_ttl=86400,
        )
    assert "mismatch" in exc.value.description


async def test_exchange_code_pkce_fail() -> None:
    row = SimpleNamespace(
        used_at=None, expires_at=NOW + timedelta(hours=1),
        client_id=CLIENT_ID, redirect_uri=LOOPBACK, code_challenge="wrong",
    )
    db = fake_session(result(row))
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.exchange_code(
            db, code="c", code_verifier="v", redirect_uri=LOOPBACK,
            client_id=CLIENT_ID, now=NOW, access_ttl=3600, refresh_ttl=86400,
        )
    assert "PKCE" in exc.value.description


async def test_exchange_code_success_with_ttl() -> None:
    verifier = "a" * 64
    row = SimpleNamespace(
        used_at=None, expires_at=NOW + timedelta(hours=1), client_id=CLIENT_ID,
        redirect_uri=LOOPBACK, code_challenge=_challenge(verifier),
        access_ttl_seconds=3600, principal_id="pid", scope="read",
    )
    db = fake_session(result(row))
    issued = await oauth_service.exchange_code(
        db, code="c", code_verifier=verifier, redirect_uri=LOOPBACK,
        client_id=CLIENT_ID, now=NOW, access_ttl=7200, refresh_ttl=86400,
    )
    assert row.used_at == NOW
    assert issued.access_token.startswith("apat_")
    assert issued.refresh_token.startswith("aprt_")
    assert issued.expires_in == 3600  # consent-TTL maßgeblich, nicht access_ttl-Param
    token_row = db.added[0]
    assert token_row.access_expires_at == NOW + timedelta(seconds=3600)
    assert token_row.refresh_expires_at == NOW + timedelta(seconds=86400)


async def test_exchange_code_success_never_expires() -> None:
    verifier = "b" * 64
    row = SimpleNamespace(
        used_at=None, expires_at=NOW + timedelta(hours=1), client_id=CLIENT_ID,
        redirect_uri=LOOPBACK, code_challenge=_challenge(verifier),
        access_ttl_seconds=None, principal_id="pid", scope="read",
    )
    db = fake_session(result(row))
    issued = await oauth_service.exchange_code(
        db, code="c", code_verifier=verifier, redirect_uri=LOOPBACK,
        client_id=CLIENT_ID, now=NOW, access_ttl=7200, refresh_ttl=86400,
    )
    assert issued.expires_in is None
    token_row = db.added[0]
    assert token_row.access_expires_at is None  # _expiry(None) → None
    assert token_row.refresh_expires_at is None


async def test_refresh_tokens_not_found() -> None:
    db = fake_session(result())
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.refresh_tokens(
            db, refresh_token="rt", client_id=CLIENT_ID, now=NOW,
            access_ttl=3600, refresh_ttl=86400,
        )
    assert "invalid or revoked" in exc.value.description


async def test_refresh_tokens_revoked() -> None:
    row = SimpleNamespace(revoked_at=NOW, client_id=CLIENT_ID, refresh_expires_at=None)
    db = fake_session(result(row))
    with pytest.raises(oauth.OAuthError):
        await oauth_service.refresh_tokens(
            db, refresh_token="rt", client_id=CLIENT_ID, now=NOW,
            access_ttl=3600, refresh_ttl=86400,
        )


async def test_refresh_tokens_client_mismatch() -> None:
    row = SimpleNamespace(revoked_at=None, client_id="other", refresh_expires_at=None)
    db = fake_session(result(row))
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.refresh_tokens(
            db, refresh_token="rt", client_id=CLIENT_ID, now=NOW,
            access_ttl=3600, refresh_ttl=86400,
        )
    assert "client mismatch" in exc.value.description


async def test_refresh_tokens_expired() -> None:
    row = SimpleNamespace(
        revoked_at=None, client_id=CLIENT_ID,
        refresh_expires_at=NOW - timedelta(seconds=1),
    )
    db = fake_session(result(row))
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.refresh_tokens(
            db, refresh_token="rt", client_id=CLIENT_ID, now=NOW,
            access_ttl=3600, refresh_ttl=86400,
        )
    assert "expired" in exc.value.description


async def test_refresh_tokens_success_rotation() -> None:
    row = SimpleNamespace(
        revoked_at=None, client_id=CLIENT_ID, refresh_expires_at=NOW + timedelta(days=30),
        access_ttl_seconds=3600, principal_id="pid", scope="read",
    )
    db = fake_session(result(row))
    issued = await oauth_service.refresh_tokens(
        db, refresh_token="rt", client_id=CLIENT_ID, now=NOW,
        access_ttl=3600, refresh_ttl=86400,
    )
    assert row.revoked_at == NOW  # altes Token rotiert
    assert issued.expires_in == 3600
    assert db.added[0].refresh_expires_at == NOW + timedelta(seconds=86400)


async def test_refresh_tokens_success_never_expires() -> None:
    row = SimpleNamespace(
        revoked_at=None, client_id=CLIENT_ID, refresh_expires_at=None,
        access_ttl_seconds=None, principal_id="pid", scope="read",
    )
    db = fake_session(result(row))
    issued = await oauth_service.refresh_tokens(
        db, refresh_token="rt", client_id=CLIENT_ID, now=NOW,
        access_ttl=3600, refresh_ttl=86400,
    )
    assert issued.expires_in is None
    assert db.added[0].refresh_expires_at is None


async def test_resolve_access_token_not_found() -> None:
    db = fake_session(result())
    assert await oauth_service.resolve_access_token(db, token="t", now=NOW) is None


async def test_resolve_access_token_revoked() -> None:
    row = SimpleNamespace(revoked_at=NOW, access_expires_at=None)
    db = fake_session(result(row))
    assert await oauth_service.resolve_access_token(db, token="t", now=NOW) is None


async def test_resolve_access_token_expired() -> None:
    row = SimpleNamespace(
        revoked_at=None, access_expires_at=NOW - timedelta(seconds=1),
        principal_id="pid", scope="read",
    )
    db = fake_session(result(row))
    assert await oauth_service.resolve_access_token(db, token="t", now=NOW) is None


async def test_resolve_access_token_valid() -> None:
    row = SimpleNamespace(
        revoked_at=None, access_expires_at=NOW + timedelta(hours=1),
        principal_id="pid", scope="read votes:write",
    )
    db = fake_session(result(row))
    out = await oauth_service.resolve_access_token(db, token="t", now=NOW)
    assert out == ("pid", "read votes:write")


async def test_resolve_access_token_never_expires() -> None:
    row = SimpleNamespace(
        revoked_at=None, access_expires_at=None, principal_id="pid", scope="read",
    )
    db = fake_session(result(row))
    out = await oauth_service.resolve_access_token(db, token="t", now=NOW)
    assert out == ("pid", "read")


# =========================================================================== #
# mcp_router
# =========================================================================== #
def test_mcp_config_requires_mcp_use_401() -> None:
    client = _build_client(ENABLED, no_principal_override=True)
    assert client.get("/api/mcp/config").status_code == 401


def test_mcp_config_forbidden_without_perm_403() -> None:
    p = Principal(sub="u", permissions={"application.read"})  # kein mcp.use
    client = _build_client(ENABLED, principal=p)
    assert client.get("/api/mcp/config").status_code == 403


def test_mcp_config_success() -> None:
    client = _build_client(ENABLED, principal=_mcp_principal())
    body = client.get("/api/mcp/config").json()
    assert body["clientId"] == CLIENT_ID
    assert body["baseUrl"] == "https://antrag.example"
    assert body["scopesSupported"] == sorted(oauth.SCOPES.keys())
    assert body["mcpServers"]["antragsplattform"]["command"] == "antragsplattform-mcp"


def test_mcp_package_not_available_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_router_mod, "_package_dir", lambda settings: None)
    client = _build_client(ENABLED, principal=_mcp_principal())
    assert client.get("/api/mcp/package").status_code == 404


def test_mcp_package_streams_tarball(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Minimal-Quellpaket aufbauen + ausgeschlossene Verzeichnisse mit hineinlegen.
    pkg = tmp_path / "mcp"
    (pkg / "antragsplattform_mcp").mkdir(parents=True)
    (pkg / "pyproject.toml").write_text("[project]\nname='x'\n")
    (pkg / "antragsplattform_mcp" / "__init__.py").write_text("")
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "junk.pyc").write_text("nope")

    monkeypatch.setattr(mcp_router_mod, "_package_dir", lambda settings: pkg)
    client = _build_client(ENABLED, principal=_mcp_principal())
    resp = client.get("/api/mcp/package")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"
    assert "antragsplattform-mcp.tar.gz" in resp.headers["content-disposition"]

    import io

    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
        names = tar.getnames()
    # ausgeschlossener __pycache__-Inhalt fehlt; gebackene _baked.py ist drin.
    assert not any("__pycache__" in n for n in names)
    assert "antragsplattform-mcp/antragsplattform_mcp/_baked.py" in names


def test_is_pkg_true_and_false(tmp_path: Path) -> None:
    bad = tmp_path / "empty"
    bad.mkdir()
    assert mcp_router_mod._is_pkg(bad) is False
    good = tmp_path / "good"
    (good / "antragsplattform_mcp").mkdir(parents=True)
    (good / "pyproject.toml").write_text("x")
    assert mcp_router_mod._is_pkg(good) is True


def test_package_dir_from_setting_valid(tmp_path: Path) -> None:
    good = tmp_path / "p"
    (good / "antragsplattform_mcp").mkdir(parents=True)
    (good / "pyproject.toml").write_text("x")
    s = load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="session-secret-0123456",
        magic_link_secret="magic-link-secret-0",
        mcp_package_dir=str(good),
    )
    assert mcp_router_mod._package_dir(s) == good


def test_package_dir_from_setting_invalid_returns_none(tmp_path: Path) -> None:
    s = load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="session-secret-0123456",
        magic_link_secret="magic-link-secret-0",
        mcp_package_dir=str(tmp_path / "nonexistent"),
    )
    assert mcp_router_mod._package_dir(s) is None


def test_package_dir_container_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    s = load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="session-secret-0123456",
        magic_link_secret="magic-link-secret-0",
    )
    mount = Path("/opt/mcp")
    monkeypatch.setattr(
        mcp_router_mod, "_is_pkg", lambda d: d == mount
    )
    assert mcp_router_mod._package_dir(s) == mount


def test_package_dir_upward_search(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    s = load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="session-secret-0123456",
        magic_link_secret="magic-link-secret-0",
    )
    parent_a = tmp_path / "a"
    parent_b = tmp_path / "b"
    found = parent_b / "mcp"

    def _is_pkg(d: Path) -> bool:
        return d == found

    monkeypatch.setattr(mcp_router_mod, "_is_pkg", _is_pkg)
    # Erster Parent matcht NICHT (Loop continue, Branch 55->53), zweiter matcht.
    monkeypatch.setattr(
        mcp_router_mod.Path,
        "resolve",
        lambda self: SimpleNamespace(parents=[parent_a, parent_b]),
    )
    assert mcp_router_mod._package_dir(s) == found


def test_package_dir_nowhere_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    s = load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="session-secret-0123456",
        magic_link_secret="magic-link-secret-0",
    )
    monkeypatch.setattr(mcp_router_mod, "_is_pkg", lambda d: False)
    monkeypatch.setattr(
        mcp_router_mod.Path, "resolve", lambda self: SimpleNamespace(parents=[])
    )
    assert mcp_router_mod._package_dir(s) is None


# =========================================================================== #
# router.py — me-helper + callback oauth-tx branch
# =========================================================================== #
def test_callback_with_oauth_tx_redirects_to_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _ok(*a: object, **k: object) -> tuple[str, PrincipalRow]:
        return "signed-sid", PrincipalRow(sub="u1")

    monkeypatch.setattr(router_mod.service, "oidc_callback", _ok)
    client = _build_client(ENABLED, no_principal_override=True)
    tx = sessions.issue_oidc_tx(ENABLED.session_secret, "st", "v", "n")
    client.cookies.set(ENABLED.oidc_tx_cookie_name, tx)
    # Laufender OAuth-AS-Login (ap_oauth_tx gesetzt) → Redirect auf /api/oauth/finish.
    client.cookies.set(ENABLED.oauth_tx_cookie_name, "anything")
    resp = client.get("/api/auth/callback?code=c&state=st")
    assert resp.status_code == 307
    assert resp.headers["location"].endswith("/api/oauth/finish")


async def test_me_gremien_helpers_with_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Direkter Aufruf der me-Helper mit Treffern (Zeilen 234-241, 257, etc.)."""
    from app.modules.admin import gremium_roles as gr

    gid = "11111111-1111-1111-1111-111111111111"

    async def _member_ids(db: object, sub: str, *a: object) -> set[str]:
        return {gid}

    async def _ids_with_perm(db: object, sub: str, perm: str, *a: object) -> set[str]:
        return {gid}

    monkeypatch.setattr(gr, "gremium_member_ids", _member_ids)
    monkeypatch.setattr(gr, "gremium_ids_with_permission", _ids_with_perm)

    gremium_row = SimpleNamespace(id=gid, name="StuPa", slug="stupa")
    # _gremien_for: gremium_member_ids → {gid}, dann SELECT-Zeilen.
    db = fake_session(result(gremium_row))
    out = await router_mod._gremien_for(db, "u1")
    assert len(out) == 1
    assert out[0].name == "StuPa"

    # _session_manage_gremien: sortierte UUID-Liste.
    out2 = await router_mod._session_manage_gremien(fake_session(), "u1")
    assert out2 == [gid]


async def test_me_gremien_for_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.admin import gremium_roles as gr

    async def _empty(db: object, sub: str, *a: object) -> set[str]:
        return set()

    monkeypatch.setattr(gr, "gremium_member_ids", _empty)
    assert await router_mod._gremien_for(fake_session(), "u1") == []


async def test_has_scoped_budget_view_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.admin import gremium_roles as gr

    gid = "22222222-2222-2222-2222-222222222222"

    # kein Mitglieds-Gremium → False (early return).
    async def _none(db: object, sub: str, *a: object) -> set[str]:
        return set()

    monkeypatch.setattr(gr, "gremium_member_ids", _none)
    assert await router_mod._has_scoped_budget_view(fake_session(), "u1") is False

    # Mitglied + Budget-Treffer (scalar) → True.
    async def _some(db: object, sub: str, *a: object) -> set[str]:
        return {gid}

    monkeypatch.setattr(gr, "gremium_member_ids", _some)
    db = fake_session()
    db.scalar_results.append("budget-id")
    assert await router_mod._has_scoped_budget_view(db, "u1") is True

    # Mitglied, aber kein Budget-Root → False (scalar None).
    db2 = fake_session()
    assert await router_mod._has_scoped_budget_view(db2, "u1") is False


async def test_in_substitute_pool_branches() -> None:
    # Treffer → True.
    hit_db = fake_session()
    hit_db.scalar_results.append("sub-id")
    assert await router_mod._in_substitute_pool(hit_db, "u1") is True
    # Kein Treffer → False.
    assert await router_mod._in_substitute_pool(fake_session(), "u1") is False


def test_me_endpoint_aggregates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Voll durch ``/auth/me`` mit gemockten Helpern (Aggregation aller Felder)."""
    gid = "33333333-3333-3333-3333-333333333333"

    async def _gremien(db: object, sub: str) -> list[object]:
        return []

    async def _manage(db: object, sub: str) -> list[str]:
        return [gid]

    async def _budget(db: object, sub: str) -> bool:
        return True

    async def _pool(db: object, sub: str) -> bool:
        return True

    monkeypatch.setattr(router_mod, "_gremien_for", _gremien)
    monkeypatch.setattr(router_mod, "_session_manage_gremien", _manage)
    monkeypatch.setattr(router_mod, "_has_scoped_budget_view", _budget)
    monkeypatch.setattr(router_mod, "_in_substitute_pool", _pool)

    app = create_app(ENABLED)

    async def _fake_db() -> AsyncIterator[object]:
        yield fake_session()

    app.dependency_overrides[get_settings] = lambda: ENABLED
    app.dependency_overrides[get_session] = _fake_db
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="u1", email="e@x.de", roles=["member"], permissions={"application.read"},
        groups={"g"},
    )
    client = TestClient(app)
    body = client.get("/api/auth/me").json()
    assert body["session_manage_gremien"] == [gid]
    assert body["has_scoped_budget_view"] is True
    assert body["in_substitute_pool"] is True


async def test_deliver_magic_link_inner_deliver_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_deliver_magic_link`` inner-``deliver`` ruft NotificationService.send_magic_link.

    Deckt den Body der inneren ``deliver``-Closure (Zeile 257-259), indem das gemockte
    ``request_magic_link`` den übergebenen ``deliver`` tatsächlich aufruft."""
    db = fake_session()

    class _ACM:
        async def __aenter__(self) -> object:
            return db

        async def __aexit__(self, *exc: object) -> bool:
            return False

    sent: list[tuple[str, str]] = []

    class _FakeNotificationService:
        def __init__(self, session: object, *, queue: object, settings: object) -> None:
            self._s = session

        async def send_magic_link(self, *, email: str, link: str) -> None:
            sent.append((email, link))

    async def _req(
        session: object, settings: object, *, email: str, application_id: object,
        deliver: object,
    ) -> None:
        # ruft die innere deliver-Closure → Body von Zeile 257-259.
        await deliver("r@x.de", "https://link")  # type: ignore[operator]

    monkeypatch.setattr(router_mod, "get_sessionmaker", lambda: _ACM)
    monkeypatch.setattr(router_mod, "mail_queue_from_pool", lambda pool: None)
    monkeypatch.setattr(router_mod, "NotificationService", _FakeNotificationService)
    monkeypatch.setattr(router_mod.service, "request_magic_link", _req)

    await router_mod._deliver_magic_link(ENABLED, "x@y.de", None, None)
    assert sent == [("r@x.de", "https://link")]
    assert db.committed == 1


# =========================================================================== #
# service.py — deactivated account
# =========================================================================== #
async def test_oidc_callback_deactivated_account_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = ENABLED

    async def _exchange(s: Settings, *, code: str, verifier: str) -> dict[str, str]:
        return {"id_token": "idt", "refresh_token": "rt"}

    async def _verify(s: Settings, *, id_token: str, nonce: str) -> OidcClaims:
        return OidcClaims(sub="s1", email="e@x.de", name="N", groups=["g"])

    monkeypatch.setattr(service.oidc, "exchange_code", _exchange)
    monkeypatch.setattr(service.oidc, "verify_id_token", _verify)

    deactivated = PrincipalRow(sub="s1")
    deactivated.active = False  # type: ignore[assignment]
    db = fake_session(result(deactivated))  # upsert findet bestehende, deaktivierte Zeile
    with pytest.raises(ForbiddenError):
        await service.oidc_callback(db, settings, code="c", verifier="v", nonce="n")


async def test_oidc_callback_email_verified_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aktiver Account + email_verified → ensure_admin/member laufen, Session entsteht."""
    settings = ENABLED

    async def _exchange(s: Settings, *, code: str, verifier: str) -> dict[str, str]:
        return {"id_token": "idt", "refresh_token": "rt"}

    async def _verify(s: Settings, *, id_token: str, nonce: str) -> OidcClaims:
        return OidcClaims(
            sub="s1", email="e@x.de", name="N", groups=["g"], email_verified=True
        )

    seen: dict[str, object] = {}

    async def _ensure_admin(db: object, s: object, row: object, *, email_verified: bool) -> None:
        seen["email_verified"] = email_verified

    async def _ensure_member(db: object, row: object) -> None:
        seen["member"] = True

    monkeypatch.setattr(service.oidc, "exchange_code", _exchange)
    monkeypatch.setattr(service.oidc, "verify_id_token", _verify)
    monkeypatch.setattr(service, "ensure_admin_for_principal", _ensure_admin)
    monkeypatch.setattr(service, "ensure_member_for_principal", _ensure_member)

    db = fake_session(result())  # neuer Principal
    cookie, row = await service.oidc_callback(
        db, settings, code="c", verifier="v", nonce="n"
    )
    assert cookie
    assert seen == {"email_verified": True, "member": True}


# =========================================================================== #
# rbac.py — vote.cast membership group
# =========================================================================== #
async def test_resolve_principal_membership_grants_vote_group() -> None:
    """Aktive Gremium-Rolle mit ``vote.cast`` → Gremium-Gruppe in groups (Zeile 113-114)."""
    row = PrincipalRow(sub="u9", email=None, display_name=None, oidc_groups=None)
    row.id = "pid"  # type: ignore[assignment]
    gid = "44444444-4444-4444-4444-444444444444"
    db = fake_session(
        result(),  # keine RoleAssignments
        # keine GroupMapping-Query, weil groups leer → wird übersprungen
        result((gid, ["vote.cast", "vote.manage"])),  # membership_rows
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert gid in p.groups


async def test_resolve_principal_membership_without_vote_cast() -> None:
    """Mitgliedschaft ohne ``vote.cast`` → keine Gruppe (else-Zweig Zeile 113)."""
    row = PrincipalRow(sub="u10", email=None, display_name=None, oidc_groups=None)
    row.id = "pid"  # type: ignore[assignment]
    gid = "55555555-5555-5555-5555-555555555555"
    db = fake_session(
        result(),  # keine RoleAssignments
        result((gid, ["vote.manage"])),  # membership ohne vote.cast
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert gid not in p.groups
    assert p.groups == set()


async def test_resolve_principal_membership_perms_none() -> None:
    """``perms`` ist None (perms or []) → kein Crash, keine Gruppe."""
    row = PrincipalRow(sub="u11", email=None, display_name=None, oidc_groups=None)
    row.id = "pid"  # type: ignore[assignment]
    gid = "66666666-6666-6666-6666-666666666666"
    db = fake_session(
        result(),
        result((gid, None)),  # perms None
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert gid not in p.groups


async def test_resolve_principal_with_assignment_and_group_mappings() -> None:
    """RoleAssignment mit/ohne Gremium + GroupMapping mit/ohne Gremium → Loop-Körper.

    Deckt: gültiges Assignment mit Gremium (groups.add), gültiges Assignment ohne
    Gremium (kein add), abgelaufenes Assignment (else-Zweig _assignment_valid),
    GroupMapping mit Gremium (Zeile 74-75) und GroupMapping ohne Gremium (Zeile 73).
    """
    row = PrincipalRow(sub="u12", email=None, display_name=None, oidc_groups=["grpA"])
    row.id = "pid"  # type: ignore[assignment]
    gid = "77777777-7777-7777-7777-777777777777"
    map_gid = "88888888-8888-8888-8888-888888888888"
    valid_g = RoleAssignment(
        role_id="r1", gremium_id=gid, valid_from=None, valid_until=None
    )
    valid_no_g = RoleAssignment(
        role_id="r2", gremium_id=None, valid_from=None, valid_until=None
    )
    expired = RoleAssignment(
        role_id="rX", gremium_id=None, valid_from=None,
        valid_until=NOW - timedelta(days=1),
    )
    map_global = GroupMapping(oidc_group="grpA", role_id="r3", gremium_id=None)
    map_scoped = GroupMapping(oidc_group="grpA", role_id="r4", gremium_id=map_gid)
    db = fake_session(
        result(valid_g, valid_no_g, expired),  # assignments
        result(map_global, map_scoped),        # group mappings
        result("application.read"),            # role permissions
        result("member"),                      # role keys
        result(),                              # membership rows
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert str(gid) in p.groups        # Assignment-Gremium
    assert str(map_gid) in p.groups    # Mapping-Gremium
    assert "grpA" in p.groups          # OIDC-Gruppe
    assert p.permissions == {"application.read"}


async def test_resolve_principal_naive_validity_window() -> None:
    """Naive ``valid_from``/``valid_until`` (DB ohne tz) → ``_as_aware``-Zweig (Zeile 32)."""
    row = PrincipalRow(sub="u13", email=None, display_name=None, oidc_groups=None)
    row.id = "pid"  # type: ignore[assignment]
    gid = "99999999-9999-9999-9999-999999999999"
    naive = RoleAssignment(
        role_id="r1",
        gremium_id=gid,
        valid_from=(NOW - timedelta(days=1)).replace(tzinfo=None),
        valid_until=(NOW + timedelta(days=1)).replace(tzinfo=None),
    )
    db = fake_session(
        result(naive),
        result(),                       # keine GroupMappings
        result("application.read"),
        result("member"),
        result(),                       # membership rows
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert str(gid) in p.groups
