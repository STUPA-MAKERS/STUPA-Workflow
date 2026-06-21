"""TDD: Auth-Endpunkte (api.md §3 »auth«) — Contract + Cookie-Flags."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.auth import router as router_mod
from app.modules.auth.models import AuthSession
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oidc import OidcError
from app.settings import Settings, get_settings, load_settings
from app.shared.errors import GoneError
from tests._support.auth_fakes import fake_session

DISABLED = load_settings(
    database_url="postgresql+asyncpg://x/y",
    session_secret="session-secret-0123",
    magic_link_secret="magic-link-secret-0",
)
ENABLED = load_settings(
    database_url="postgresql+asyncpg://x/y",
    session_secret="session-secret-0123",
    magic_link_secret="magic-link-secret-0",
    oidc_issuer="https://kc.example/realms/app",
    oidc_client_id="antrag",
    oidc_client_secret="client-secret-01234",
    oidc_redirect_url="https://antrag.example/api/auth/callback",
    cookie_secure=False,
)


def _client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)

    async def _fake_db() -> AsyncIterator[object]:
        yield fake_session()

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = _fake_db
    return iter([TestClient(app, follow_redirects=False)])


@pytest.fixture
def disabled_client() -> Iterator[TestClient]:
    yield from _client(DISABLED)


@pytest.fixture
def enabled_client() -> Iterator[TestClient]:
    yield from _client(ENABLED)


def _csrf(client: TestClient, settings: Settings) -> dict[str, str]:
    """CSRF-Cookie setzen + passenden Header liefern (Double-Submit, security.md §10).

    Nötig, sobald der Request ein Auth-Cookie trägt (z. B. Logout mit Session-Cookie)."""
    token = "csrf-test-token"
    client.cookies.set(settings.csrf_cookie_name, token)
    return {settings.csrf_header_name: token}


# --------------------------------------------------------------------------- #
# login
# --------------------------------------------------------------------------- #
def test_login_disabled_returns_404(disabled_client: TestClient) -> None:
    assert disabled_client.get("/api/auth/login").status_code == 404


def test_login_redirects_to_keycloak(enabled_client: TestClient) -> None:
    resp = enabled_client.get("/api/auth/login")
    assert resp.status_code == 307
    assert resp.headers["location"].startswith("https://kc.example/realms/app/")
    assert ENABLED.oidc_tx_cookie_name in resp.headers.get("set-cookie", "")


# --------------------------------------------------------------------------- #
# callback
# --------------------------------------------------------------------------- #
def test_callback_disabled_returns_404(disabled_client: TestClient) -> None:
    resp = disabled_client.get("/api/auth/callback?code=c&state=s")
    assert resp.status_code == 404


def test_callback_missing_tx_returns_400(enabled_client: TestClient) -> None:
    resp = enabled_client.get("/api/auth/callback?code=c&state=s")
    assert resp.status_code == 400


def test_callback_state_mismatch_returns_400(enabled_client: TestClient) -> None:
    from app.modules.auth import sessions

    tx = sessions.issue_oidc_tx(ENABLED.session_secret, "real-state", "v", "n")
    enabled_client.cookies.set(ENABLED.oidc_tx_cookie_name, tx)
    resp = enabled_client.get("/api/auth/callback?code=c&state=other-state")
    assert resp.status_code == 400


def test_callback_oidc_error_returns_400(
    enabled_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.auth import sessions

    async def _boom(*a: object, **k: object) -> tuple[str, object]:
        raise OidcError("nope")

    monkeypatch.setattr(router_mod.service, "oidc_callback", _boom)
    tx = sessions.issue_oidc_tx(ENABLED.session_secret, "st", "v", "n")
    enabled_client.cookies.set(ENABLED.oidc_tx_cookie_name, tx)
    resp = enabled_client.get("/api/auth/callback?code=c&state=st")
    assert resp.status_code == 400


def test_callback_success_sets_session(
    enabled_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.auth import sessions

    async def _ok(*a: object, **k: object) -> tuple[str, PrincipalRow]:
        return "signed-sid", PrincipalRow(sub="u1")

    monkeypatch.setattr(router_mod.service, "oidc_callback", _ok)
    tx = sessions.issue_oidc_tx(ENABLED.session_secret, "st", "v", "n")
    enabled_client.cookies.set(ENABLED.oidc_tx_cookie_name, tx)
    resp = enabled_client.get("/api/auth/callback?code=c&state=st")
    assert resp.status_code == 307
    assert ENABLED.session_cookie_name in resp.headers.get("set-cookie", "")


# --------------------------------------------------------------------------- #
# logout
# --------------------------------------------------------------------------- #
def test_logout_without_cookie_local_only(enabled_client: TestClient) -> None:
    resp = enabled_client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"logout_url": None}


def test_logout_with_cookie_returns_rp_logout_url(
    enabled_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _del(*a: object, **k: object) -> AuthSession:
        return AuthSession(sid="s", principal_id="p", id_token="idt")

    monkeypatch.setattr(router_mod.sessions, "delete_principal_session", _del)
    enabled_client.cookies.set(ENABLED.session_cookie_name, "x")
    resp = enabled_client.post("/api/auth/logout", headers=_csrf(enabled_client, ENABLED))
    assert resp.status_code == 200
    url = resp.json()["logout_url"]
    assert url is not None
    assert "/protocol/openid-connect/logout" in url
    assert "id_token_hint=idt" in url


def test_logout_revokes_applicant_session(
    enabled_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Logout widerruft auch eine vorhandene Applicant-Session + löscht ihr Cookie."""
    seen: dict[str, object] = {}

    async def _del_ap(*a: object, **k: object) -> None:
        seen["cookie_value"] = k.get("cookie_value")
        return None

    monkeypatch.setattr(router_mod.sessions, "delete_applicant_session", _del_ap)
    enabled_client.cookies.set(ENABLED.applicant_cookie_name, "ap-x")
    resp = enabled_client.post("/api/auth/logout", headers=_csrf(enabled_client, ENABLED))
    assert resp.status_code == 200
    assert seen["cookie_value"] == "ap-x"
    assert ENABLED.applicant_cookie_name in resp.headers.get("set-cookie", "")


def test_logout_disabled_oidc_no_url(
    disabled_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _del(*a: object, **k: object) -> AuthSession:
        return AuthSession(sid="s", principal_id="p", id_token="idt")

    monkeypatch.setattr(router_mod.sessions, "delete_principal_session", _del)
    disabled_client.cookies.set(DISABLED.session_cookie_name, "x")
    resp = disabled_client.post(
        "/api/auth/logout", headers=_csrf(disabled_client, DISABLED)
    )
    assert resp.status_code == 200
    assert resp.json() == {"logout_url": None}


# --------------------------------------------------------------------------- #
# me
# --------------------------------------------------------------------------- #
def test_me_unauthenticated_401(enabled_client: TestClient) -> None:
    assert enabled_client.get("/api/auth/me").status_code == 401


def test_me_returns_principal() -> None:
    app = create_app(ENABLED)

    async def _fake_db() -> AsyncIterator[object]:
        yield fake_session()

    app.dependency_overrides[get_settings] = lambda: ENABLED
    app.dependency_overrides[get_session] = _fake_db
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="u1", email="e@x.de", roles=["member"], permissions={"application.read"},
        groups={"stupa"},
    )
    client = TestClient(app)
    body = client.get("/api/auth/me").json()
    assert body == {
        "sub": "u1",
        "email": "e@x.de",
        "display_name": None,
        "roles": ["member"],
        "permissions": ["application.read"],
        "groups": ["stupa"],
        "gremien": [],
        "session_manage_gremien": [],
        "has_scoped_budget_view": False,
        "in_substitute_pool": False,
    }


# --------------------------------------------------------------------------- #
# magic-link
# --------------------------------------------------------------------------- #
def test_magic_link_always_202(
    enabled_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled: list[tuple[object, ...]] = []

    async def _capture(
        settings: object, email: str, application_id: object, pool: object
    ) -> None:
        scheduled.append((email, application_id))

    # Hintergrund-Task abfangen (kein realer DB-Zugriff im Test).
    monkeypatch.setattr(router_mod, "_deliver_magic_link", _capture)
    resp = enabled_client.post("/api/auth/magic-link", json={"email": "x@y.de"})
    assert resp.status_code == 202
    assert resp.json() == {"status": "accepted"}
    # Arbeit wurde als Background-Task geplant (konstante Antwortzeit).
    assert scheduled == [("x@y.de", None)]


def test_magic_link_invalid_email_422(enabled_client: TestClient) -> None:
    resp = enabled_client.post("/api/auth/magic-link", json={"email": "not-an-email"})
    assert resp.status_code == 422


def test_magic_link_malformed_altcha_422(enabled_client: TestClient) -> None:
    # Strukturell ungültiges altcha (Steuerzeichen) → 422 VOR der Logik, auch bei
    # ausgeschalteter Verifikation (Contract `negative_data_rejection`, Issue #23).
    resp = enabled_client.post(
        "/api/auth/magic-link", json={"email": "x@y.de", "altcha": "ZÈ♯æL¾&"}
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "body.altcha"


def test_magic_link_well_formed_altcha_202(
    enabled_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Strukturell gültige Lösung (Krypto irrelevant, Verifikation aus) → Happy-Path 202.
    from app.shared.altcha import create_challenge, solve_challenge

    async def _noop(settings: object, email: str, application_id: object, pool: object) -> None:
        return None

    monkeypatch.setattr(router_mod, "_deliver_magic_link", _noop)
    solution = solve_challenge(create_challenge("altcha-test-secret-0123", max_number=50))
    resp = enabled_client.post(
        "/api/auth/magic-link", json={"email": "x@y.de", "altcha": solution}
    )
    assert resp.status_code == 202


async def test_deliver_magic_link_opens_session_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = fake_session()

    class _ACM:
        async def __aenter__(self) -> object:
            return db

        async def __aexit__(self, *exc: object) -> bool:
            return False

    called: list[str] = []

    async def _req(session: object, settings: object, *, email: str, **k: object) -> None:
        called.append(email)

    monkeypatch.setattr(router_mod, "get_sessionmaker", lambda: _ACM)
    monkeypatch.setattr(router_mod.service, "request_magic_link", _req)
    await router_mod._deliver_magic_link(ENABLED, "x@y.de", None, None)
    assert called == ["x@y.de"]
    assert db.committed == 1


def test_magic_link_verify_ok(
    enabled_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_uuid = "11111111-1111-1111-1111-111111111111"

    async def _verify(*a: object, **k: object) -> tuple[str, str, str]:
        return app_uuid, "edit", "applicant-token"

    monkeypatch.setattr(router_mod.service, "verify_magic_link", _verify)
    resp = enabled_client.post("/api/auth/magic-link/verify", json={"token": "tok"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["application_id"] == app_uuid
    assert body["scope"] == "edit"
    assert ENABLED.applicant_cookie_name in resp.headers.get("set-cookie", "")


def test_magic_link_verify_gone(
    enabled_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _verify(*a: object, **k: object) -> tuple[str, str, str]:
        raise GoneError("expired")

    monkeypatch.setattr(router_mod.service, "verify_magic_link", _verify)
    resp = enabled_client.post("/api/auth/magic-link/verify", json={"token": "tok"})
    assert resp.status_code == 410
