"""Zusatz-Coverage (Misc): search / deps / middleware / admin+applications-Router.

Treibt die bisher unerreichten Zweige der fünf Ziel-Module auf ~100 %:

* ``app.search``         — Postgres-Trigram **und** ILIKE-Fallback, ein- vs. mehrspaltig,
  ``dialect_of`` mit/ohne gebundene Engine, leere Query.
* ``app.deps``           — OAuth-Bearer-Pfad (``apat_``) inkl. ungültig/inaktiv/abgelaufen,
  ``require_any_permission`` (401/403/ok).
* ``app.middleware``     — CSRF enforce/fail/cookie-set, Default-Write-Rate-Limit 429.
* ``app.modules.admin.router``        — Service-Factory-Deps, restliche Endpunkt-Bodies
  (Gremium löschen, Gremium-Rollen/Mitgliedschaften, globaler Flow, Principal-Toggle,
  Rolle löschen) + PWA-Manifest.
* ``app.modules.applications.router`` — Service-Factory + injizierbare Sender,
  ``_deliver_magic_link`` / ``_deliver_comment_mails`` (gefakte Sessionmaker), die
  ``list_tasks``-/``get_form``-Routen und der DSGVO-Löschantrag.

Alle Tests sind reine Unit-Tests: keine echte DB, kein Redis, kein Netzwerk.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import column, func, literal
from starlette.requests import Request
from starlette.responses import Response

from app import deps, middleware
from app import search as search_mod
from app.deps import (
    Principal,
    get_current_principal,
    require_any_permission,
)
from app.main import create_app
from app.middleware import (
    CsrfMiddleware,
    DefaultWriteRateLimitMiddleware,
)
from app.modules.admin.branding import Branding
from app.modules.admin.router import (
    get_config_service,
    get_gremium_role_service,
    get_site_config_service,
)
from app.modules.admin.schemas import (
    FlowVersionOut,
    GremiumOut,
    GremiumRoleOut,
    PrincipalOut,
    PublicSiteConfigOut,
    RoleOut,
    SiteConfigOut,
)
from app.modules.applications.router import (
    _deliver_comment_mails,
    _deliver_magic_link,
    get_applications_service,
    get_comment_mail_sender,
    get_magic_link_sender,
)
from app.modules.applications.schemas import ApplicationListItem, StateOut
from app.settings import Settings, load_settings
from app.shared.errors import ForbiddenError, UnauthorizedError
from app.shared.ratelimit import RateLimitResult

SECRET = "misc-secret-0123456789"


def _settings(**over: object) -> Settings:
    return load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret=SECRET,
        magic_link_secret="magic-link-secret-0",
        **over,
    )


def _request(
    *,
    method: str = "GET",
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> Request:
    raw: list[tuple[bytes, bytes]] = []
    if cookies:
        raw.append(
            (b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode())
        )
    for k, v in (headers or {}).items():
        raw.append((k.lower().encode(), v.encode()))
    return Request(
        {
            "type": "http",
            "method": method,
            "headers": raw,
            "query_string": b"",
            "client": ("203.0.113.7", 12345),
        }
    )


# =========================================================================== #
# app.search
# =========================================================================== #
def test_dialect_of_without_bind_defaults_postgres() -> None:
    """Ohne gebundene Engine fällt ``dialect_of`` auf den Prod-Default zurück."""
    sess = SimpleNamespace(bind=None)
    assert search_mod.dialect_of(sess) == "postgresql"  # type: ignore[arg-type]


def test_dialect_of_with_bind_reports_dialect_name() -> None:
    bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    sess = SimpleNamespace(bind=bind)
    assert search_mod.dialect_of(sess) == "sqlite"  # type: ignore[arg-type]


def test_trigram_rank_postgres_single_column() -> None:
    """Eine Spalte → ``rank`` ist die einzelne ``word_similarity`` (kein ``greatest``)."""
    col = column("title")
    where, rank = search_mod.trigram_rank("foo", [col], threshold=0.3)
    txt = str(rank)
    assert "word_similarity" in txt
    assert "greatest" not in txt
    # WHERE ist ein Vergleich ``rank > threshold``.
    assert ">" in str(where)


def test_trigram_rank_postgres_multi_column_uses_greatest() -> None:
    """Mehrere Spalten → ``greatest(...)`` über alle Spalten-Ähnlichkeiten."""
    where, rank = search_mod.trigram_rank(
        "  needle  ", [column("a"), column("b")], dialect="postgresql"
    )
    assert "greatest" in str(rank)
    assert ">" in str(where)


def test_trigram_rank_sqlite_fallback_uses_ilike_and_zero_rank() -> None:
    """Nicht-Postgres → ILIKE-Substring-OR und konstanter Rang ``0.0``."""
    where, rank = search_mod.trigram_rank(
        "term", [column("a"), column("b")], dialect="sqlite"
    )
    # Konstanter 0.0-Rang (literal) erlaubt bedingungsloses ORDER BY rank.
    assert isinstance(rank, type(literal(0.0)))
    where_txt = str(where).lower()
    assert "like" in where_txt
    # OR über alle Spalten (zwei coalesce-Ausdrücke).
    assert " or " in where_txt


def test_trigram_rank_strips_empty_query() -> None:
    """Leerer/weißraum-Query wird defensiv gestrippt (kein Crash)."""
    where, rank = search_mod.trigram_rank("   ", [column("a")], dialect="sqlite")
    assert where is not None and rank is not None


def test_trigram_rank_none_query_postgres() -> None:
    """``None``-artige (leere) Query auch im Postgres-Zweig abgefangen."""
    where, rank = search_mod.trigram_rank("", [func.coalesce(column("x"), "")])
    assert "word_similarity" in str(rank)


# =========================================================================== #
# app.deps — OAuth-Bearer-Pfad + require_any_permission
# =========================================================================== #
def test_principal_bearer_token_apat_prefix() -> None:
    req = _request(headers={"Authorization": "Bearer apat_tok123"})
    assert deps._principal_bearer_token(req) == "apat_tok123"


def test_principal_bearer_token_non_apat_ignored() -> None:
    # Signiertes Applicant-Bearer (kein apat_) wird hier ignoriert → None.
    req = _request(headers={"Authorization": "Bearer some.signed.applicant"})
    assert deps._principal_bearer_token(req) is None


def test_principal_bearer_token_no_authorization_header() -> None:
    assert deps._principal_bearer_token(_request()) is None


async def test_principal_from_access_token_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _none(*a: object, **k: object) -> None:
        return None

    monkeypatch.setattr(deps.oauth_service, "resolve_access_token", _none)
    out = await deps._principal_from_access_token(
        SimpleNamespace(), "apat_x", datetime.now(UTC)  # type: ignore[arg-type]
    )
    assert out is None


async def test_principal_from_access_token_principal_row_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _resolve(*a: object, **k: object) -> tuple[Any, str]:
        return (uuid4(), "read")

    monkeypatch.setattr(deps.oauth_service, "resolve_access_token", _resolve)

    class _DB:
        async def execute(self, _stmt: object) -> Any:
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    out = await deps._principal_from_access_token(
        _DB(), "apat_x", datetime.now(UTC)  # type: ignore[arg-type]
    )
    assert out is None


async def test_principal_from_access_token_inactive_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _resolve(*a: object, **k: object) -> tuple[Any, str]:
        return (uuid4(), "read")

    monkeypatch.setattr(deps.oauth_service, "resolve_access_token", _resolve)

    class _DB:
        async def execute(self, _stmt: object) -> Any:
            return SimpleNamespace(
                scalar_one_or_none=lambda: SimpleNamespace(active=False)
            )

    out = await deps._principal_from_access_token(
        _DB(), "apat_x", datetime.now(UTC)  # type: ignore[arg-type]
    )
    assert out is None


async def test_principal_from_access_token_ok_caps_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gültiges Token → RBAC-Principal, dessen Permissions auf den Scope gekappt sind."""

    async def _resolve(*a: object, **k: object) -> tuple[Any, str]:
        return (uuid4(), "read")

    async def _rbac(*a: object, **k: object) -> Principal:
        return Principal(sub="mcp", roles=["admin"], permissions={"x"})

    monkeypatch.setattr(deps.oauth_service, "resolve_access_token", _resolve)
    monkeypatch.setattr(deps.rbac, "resolve_principal", _rbac)

    class _DB:
        async def execute(self, _stmt: object) -> Any:
            return SimpleNamespace(
                scalar_one_or_none=lambda: SimpleNamespace(active=True)
            )

    out = await deps._principal_from_access_token(
        _DB(), "apat_x", datetime.now(UTC)  # type: ignore[arg-type]
    )
    assert out is not None
    # Scope-Kappung gesetzt (nicht None) — der Admin-Bypass wird dadurch neutralisiert.
    assert out.scope_permissions is not None


async def test_get_current_principal_uses_oauth_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``get_current_principal`` zweigt bei ``apat_``-Bearer auf den OAuth-Pfad ab."""
    sentinel = Principal(sub="mcp")

    async def _from_token(*a: object, **k: object) -> Principal:
        return sentinel

    monkeypatch.setattr(deps, "_principal_from_access_token", _from_token)
    req = _request(headers={"Authorization": "Bearer apat_tok"})
    out = await deps.get_current_principal(req, SimpleNamespace(), _settings())  # type: ignore[arg-type]
    assert out is sentinel


def test_require_any_permission_no_principal_401() -> None:
    with pytest.raises(UnauthorizedError):
        require_any_permission("a", "b")(principal=None)


def test_require_any_permission_missing_all_403() -> None:
    p = Principal(sub="u", permissions={"c"})
    with pytest.raises(ForbiddenError):
        require_any_permission("a", "b")(principal=p)


def test_require_any_permission_ok_when_one_matches() -> None:
    p = Principal(sub="u", permissions={"b"})
    assert require_any_permission("a", "b")(principal=p) is p


# =========================================================================== #
# app.middleware — CSRF + Default-Write-Rate-Limit (Klassen direkt getrieben)
# =========================================================================== #
async def _passthrough(_request: Request) -> Response:
    """Minimaler ``call_next``: liefert eine Response mit einem headers-/cookies-Stub."""
    return cast("Response", _FakeResponse())


class _FakeResponse:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.set_cookies: list[dict[str, Any]] = []
        self.status_code = 200

    def set_cookie(self, name: str, value: str, **kw: Any) -> None:
        self.set_cookies.append({"name": name, "value": value, **kw})


async def test_csrf_blocks_unsafe_without_token() -> None:
    """Unsichere Methode + Auth-Cookie + kein Bearer + fehlendes CSRF-Token → 403."""
    mw = CsrfMiddleware(app=object(), settings=_settings())
    req = _request(method="POST", cookies={"ap_session": "sid"})
    resp = await mw.dispatch(req, _passthrough)
    assert resp.status_code == 403
    body = bytes(resp.body).decode()
    assert "csrf_failed" in body


async def test_csrf_blocks_when_tokens_mismatch() -> None:
    mw = CsrfMiddleware(app=object(), settings=_settings())
    req = _request(
        method="POST",
        cookies={"ap_session": "sid", "XSRF-TOKEN": "aaa"},
        headers={"X-XSRF-TOKEN": "bbb"},
    )
    resp = await mw.dispatch(req, _passthrough)
    assert resp.status_code == 403


async def test_csrf_passes_with_matching_tokens_and_no_recookie() -> None:
    """Stimmige Tokens passieren; vorhandenes CSRF-Cookie wird nicht neu gesetzt."""
    mw = CsrfMiddleware(app=object(), settings=_settings())
    req = _request(
        method="POST",
        cookies={"ap_session": "sid", "XSRF-TOKEN": "tok"},
        headers={"X-XSRF-TOKEN": "tok"},
    )
    resp = await mw.dispatch(req, _passthrough)
    assert resp.status_code == 200
    # Cookie war schon da → kein erneutes Set-Cookie.
    assert cast("Any", resp).set_cookies == []


async def test_csrf_sets_cookie_when_missing() -> None:
    """Sichere Methode ohne CSRF-Cookie → es wird auf der Antwort ausgestellt."""
    mw = CsrfMiddleware(app=object(), settings=_settings(cookie_secure=False))
    req = _request(method="GET")
    resp = await mw.dispatch(req, _passthrough)
    assert resp.status_code == 200
    assert any(c["name"] == "XSRF-TOKEN" for c in cast("Any", resp).set_cookies)


async def test_csrf_disabled_passes_and_no_cookie() -> None:
    """Bei ``csrf_enabled=False`` keine Erzwingung und kein Cookie-Set."""
    mw = CsrfMiddleware(app=object(), settings=_settings(csrf_enabled=False))
    req = _request(method="POST", cookies={"ap_session": "sid"})
    resp = await mw.dispatch(req, _passthrough)
    assert resp.status_code == 200
    assert cast("Any", resp).set_cookies == []


async def test_csrf_bearer_request_exempt() -> None:
    """Bearer-authentifizierte (nicht CSRF-fähige) Requests sind ausgenommen."""
    mw = CsrfMiddleware(app=object(), settings=_settings())
    req = _request(
        method="POST",
        cookies={"ap_session": "sid"},
        headers={"Authorization": "Bearer apat_x"},
    )
    resp = await mw.dispatch(req, _passthrough)
    assert resp.status_code == 200


async def test_csrf_default_settings_branch() -> None:
    """``CsrfMiddleware`` ohne explizite Settings nutzt ``get_settings()``."""
    mw = CsrfMiddleware(app=object())
    assert mw._settings is not None
    # Safe-Methode, kein Auth-Cookie → einfacher Durchlass.
    resp = await mw.dispatch(_request(), _passthrough)
    assert resp.status_code == 200


class _Limiter:
    def __init__(self, allowed: bool, retry_after: int = 0) -> None:
        self._result = RateLimitResult(allowed=allowed, retry_after=retry_after)
        self.calls: list[tuple[str, int, int]] = []

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        self.calls.append((key, limit, window_seconds))
        return self._result


async def test_write_rate_limit_allows_under_limit() -> None:
    limiter = _Limiter(allowed=True)
    mw = DefaultWriteRateLimitMiddleware(
        app=object(), settings=_settings(), limiter=limiter
    )
    req = _request(method="POST")
    resp = await mw.dispatch(req, _passthrough)
    assert resp.status_code == 200
    assert limiter.calls and limiter.calls[0][1] == 100  # rl_default_write_per_hour


async def test_write_rate_limit_blocks_over_limit_429() -> None:
    limiter = _Limiter(allowed=False, retry_after=-5)
    mw = DefaultWriteRateLimitMiddleware(
        app=object(), settings=_settings(), limiter=limiter
    )
    req = _request(method="DELETE")
    resp = await mw.dispatch(req, _passthrough)
    assert resp.status_code == 429
    # Retry-After auf >=0 geklemmt (max(0, -5) == 0).
    assert resp.headers["Retry-After"] == "0"
    assert resp.media_type == middleware.PROBLEM_JSON


async def test_write_rate_limit_skips_safe_methods() -> None:
    limiter = _Limiter(allowed=False)
    mw = DefaultWriteRateLimitMiddleware(
        app=object(), settings=_settings(), limiter=limiter
    )
    resp = await mw.dispatch(_request(method="GET"), _passthrough)
    assert resp.status_code == 200
    assert limiter.calls == []  # GET wird nie gegen das Limit geprüft


async def test_write_rate_limit_default_limiter_from_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ohne injizierten Limiter holt die Middleware ihn via ``get_rate_limiter``."""
    fallback = _Limiter(allowed=True)
    monkeypatch.setattr(
        middleware, "get_rate_limiter", lambda _req, _settings: fallback
    )
    mw = DefaultWriteRateLimitMiddleware(app=object(), settings=_settings())
    resp = await mw.dispatch(_request(method="PATCH"), _passthrough)
    assert resp.status_code == 200
    assert fallback.calls  # der Fallback-Limiter wurde benutzt


# =========================================================================== #
# app.modules.admin.router — Service-Factories + Rest-Endpunkte
# =========================================================================== #
def test_admin_service_factories_construct() -> None:
    """Die drei Service-Factory-Deps liefern den jeweiligen Service über die Session."""
    from app.modules.admin.gremium_roles import GremiumRoleService
    from app.modules.admin.service import ConfigService
    from app.modules.admin.site_config_service import SiteConfigService

    sess = SimpleNamespace()
    assert isinstance(get_config_service(sess), ConfigService)  # type: ignore[arg-type]
    assert isinstance(get_site_config_service(sess), SiteConfigService)  # type: ignore[arg-type]
    assert isinstance(get_gremium_role_service(sess), GremiumRoleService)  # type: ignore[arg-type]


class _AdminConfigFake:
    def __init__(self) -> None:
        self.deleted_gremium: Any = None
        self.toggled: tuple[Any, bool] | None = None
        self.deleted_role: Any = None

    async def delete_gremium(self, gremium_id: Any, actor: str) -> None:
        self.deleted_gremium = gremium_id

    async def create_global_flow_version(self, payload: Any, actor: str) -> FlowVersionOut:
        return FlowVersionOut(id=uuid4(), version=3, active=payload.activate)

    async def set_principal_active(
        self, principal_id: Any, active: bool, actor: str
    ) -> PrincipalOut:
        self.toggled = (principal_id, active)
        return PrincipalOut(
            id=principal_id,
            sub="kc|max",
            email="m@x.de",
            display_name="Max",
            last_login=None,
            assignments=[],
        )

    async def delete_role(self, role_id: Any, actor: str) -> None:
        self.deleted_role = role_id

    # Reads, die die Gates der Endpunkte (Principal-Injektion) benötigen.
    async def list_roles(self) -> list[RoleOut]:
        return []


class _GremiumRolesFake:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def list_roles(self, gremium_id: Any) -> list[GremiumRoleOut]:
        return []

    async def create_role(self, gremium_id: Any, payload: Any, actor: str) -> GremiumRoleOut:
        self.events.append("create_role")
        return GremiumRoleOut(
            id=uuid4(),
            gremium_id=gremium_id,
            key=payload.key,
            name=getattr(payload, "name", {}) or {},
            forced=False,
            permissions=list(getattr(payload, "permissions", []) or []),
        )

    async def update_role(self, role_id: Any, payload: Any, actor: str) -> GremiumRoleOut:
        self.events.append("update_role")
        return GremiumRoleOut(
            id=role_id,
            gremium_id=uuid4(),
            key="member",
            name={"de": "Mitglied"},
            forced=False,
            permissions=[],
        )

    async def delete_role(self, role_id: Any, actor: str) -> None:
        self.events.append("delete_role")

    async def create_membership(
        self, gremium_id: Any, payload: Any, actor: str
    ) -> Any:
        from app.modules.admin.schemas import GremiumMembershipOut

        self.events.append("create_membership")
        return GremiumMembershipOut(
            id=uuid4(),
            principal_id=payload.principal_id,
            gremium_id=gremium_id,
            gremium_role_id=payload.gremium_role_id,
            valid_from=None,
            valid_until=None,
        )

    async def delete_membership(self, membership_id: Any, actor: str) -> None:
        self.events.append("delete_membership")


class _SiteFake:
    async def manifest(self) -> dict[str, Any]:
        return {"name": "Antrag", "short_name": "A", "icons": []}

    async def get(self) -> SiteConfigOut:
        return SiteConfigOut(
            version=1, active=Branding(), draft=Branding(), has_draft_changes=False
        )

    async def public(self) -> PublicSiteConfigOut:
        return PublicSiteConfigOut(version=1, branding=Branding())


@pytest.fixture
def admin_app() -> tuple[FastAPI, _AdminConfigFake, _GremiumRolesFake, _SiteFake]:
    application = create_app()
    cfg, groles, site = _AdminConfigFake(), _GremiumRolesFake(), _SiteFake()
    application.dependency_overrides[get_config_service] = lambda: cfg
    application.dependency_overrides[get_gremium_role_service] = lambda: groles
    application.dependency_overrides[get_site_config_service] = lambda: site
    application.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", roles=["admin"]
    )
    return application, cfg, groles, site


def test_admin_delete_gremium_204(
    admin_app: tuple[FastAPI, _AdminConfigFake, _GremiumRolesFake, _SiteFake],
) -> None:
    application, cfg, *_ = admin_app
    client = TestClient(application)
    gid = uuid4()
    assert client.delete(f"/api/admin/gremien/{gid}").status_code == 204
    assert str(cfg.deleted_gremium) == str(gid)


def test_admin_create_global_flow_201(
    admin_app: tuple[FastAPI, _AdminConfigFake, _GremiumRolesFake, _SiteFake],
) -> None:
    application, *_ = admin_app
    client = TestClient(application)
    r = client.post(
        "/api/admin/flow-versions/global",
        json={"graph": {"states": [], "transitions": [], "layout": None}},
    )
    assert r.status_code == 201
    assert r.json()["version"] == 3


def test_admin_patch_principal_toggle_active(
    admin_app: tuple[FastAPI, _AdminConfigFake, _GremiumRolesFake, _SiteFake],
) -> None:
    application, cfg, *_ = admin_app
    client = TestClient(application)
    pid = uuid4()
    r = client.patch(f"/api/admin/principals/{pid}", json={"active": False})
    assert r.status_code == 200
    assert cfg.toggled == (pid, False)


def test_admin_delete_role_204(
    admin_app: tuple[FastAPI, _AdminConfigFake, _GremiumRolesFake, _SiteFake],
) -> None:
    application, cfg, *_ = admin_app
    client = TestClient(application)
    rid = uuid4()
    assert client.delete(f"/api/admin/roles/{rid}").status_code == 204
    assert str(cfg.deleted_role) == str(rid)


def test_admin_gremium_role_crud(
    admin_app: tuple[FastAPI, _AdminConfigFake, _GremiumRolesFake, _SiteFake],
) -> None:
    application, _cfg, groles, _site = admin_app
    client = TestClient(application)
    gid, rid = uuid4(), uuid4()
    created = client.post(
        f"/api/admin/gremien/{gid}/roles",
        json={"key": "kasse", "name": {"de": "Kasse"}, "permissions": ["vote.cast"]},
    )
    assert created.status_code == 201
    patched = client.patch(
        f"/api/admin/gremium-roles/{rid}", json={"name": {"de": "Neu"}}
    )
    assert patched.status_code == 200
    deleted = client.delete(f"/api/admin/gremium-roles/{rid}")
    assert deleted.status_code == 204
    assert {"create_role", "update_role", "delete_role"} <= set(groles.events)


def test_admin_gremium_membership_create_delete(
    admin_app: tuple[FastAPI, _AdminConfigFake, _GremiumRolesFake, _SiteFake],
) -> None:
    application, _cfg, groles, _site = admin_app
    client = TestClient(application)
    gid, mid = uuid4(), uuid4()
    created = client.post(
        f"/api/admin/gremien/{gid}/memberships",
        json={"principalId": str(uuid4()), "gremiumRoleId": str(uuid4())},
    )
    assert created.status_code == 201
    deleted = client.delete(f"/api/admin/gremium-memberships/{mid}")
    assert deleted.status_code == 204
    assert {"create_membership", "delete_membership"} <= set(groles.events)


def test_admin_manifest_webmanifest(
    admin_app: tuple[FastAPI, _AdminConfigFake, _GremiumRolesFake, _SiteFake],
) -> None:
    """PWA-Manifest: auth-frei, application/manifest+json, Cache-Header."""
    application, *_ = admin_app
    client = TestClient(application)
    r = client.get("/api/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    assert r.headers["cache-control"] == "public, max-age=300"
    assert r.json()["name"] == "Antrag"


# =========================================================================== #
# app.modules.applications.router — Factory, Sender, list_tasks/form, erasure
# =========================================================================== #
def test_applications_service_factory_and_sender_getters() -> None:
    from app.modules.applications.service import ApplicationsService

    svc = get_applications_service(SimpleNamespace())  # type: ignore[arg-type]
    assert isinstance(svc, ApplicationsService)
    # Default-Sender sind die ungetauschten Modul-Funktionen.
    assert get_magic_link_sender() is _deliver_magic_link
    assert get_comment_mail_sender() is _deliver_comment_mails


class _FakeMagicSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class _FakeSessionmaker:
    """Async-Contextmanager-Sessionmaker, der eine vorgegebene Session liefert."""

    def __init__(self, session: object) -> None:
        self._session = session

    def __call__(self) -> _FakeSessionmaker:
        return self

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


async def test_deliver_magic_link_invokes_request_magic_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_deliver_magic_link`` öffnet eine eigene Session, ruft den Auth-Service + commit."""
    import app.modules.applications.router as ar

    fake_db = _FakeMagicSession()
    monkeypatch.setattr(ar, "get_sessionmaker", lambda: _FakeSessionmaker(fake_db))
    monkeypatch.setattr(ar, "mail_queue_from_pool", lambda _pool: None)

    seen: dict[str, Any] = {}

    async def _request_magic_link(db, settings, *, email, application_id, deliver):  # noqa: ANN001
        seen["email"] = email
        seen["application_id"] = application_id
        # Den injizierten Deliver einmal aufrufen (deckt die innere Closure ab).
        await deliver(email, "https://link/x")

    # NotificationService.send_magic_link darf nicht den echten Mailer berühren.
    class _NS:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        async def send_magic_link(self, *, email: str, link: str) -> None:
            seen["delivered"] = (email, link)

    monkeypatch.setattr(ar.auth_service, "request_magic_link", _request_magic_link)
    monkeypatch.setattr(ar, "NotificationService", _NS)

    aid = uuid4()
    await _deliver_magic_link(_settings(), "user@example.org", aid, pool=None)
    assert seen["email"] == "user@example.org"
    assert seen["application_id"] == aid
    assert seen["delivered"] == ("user@example.org", "https://link/x")
    assert fake_db.committed is True


async def test_deliver_comment_mails_invokes_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_deliver_comment_mails`` öffnet die Session und ruft ``send_comment_notifications``."""
    import app.modules.applications.router as ar
    import app.modules.notifications.comments as comments_mod

    fake_db = _FakeMagicSession()
    monkeypatch.setattr(ar, "get_sessionmaker", lambda: _FakeSessionmaker(fake_db))
    monkeypatch.setattr(ar, "mail_queue_from_pool", lambda _pool: None)

    captured: dict[str, Any] = {}

    async def _send(  # noqa: ANN001
        session,
        *,
        queue,
        settings,
        application_id,
        comment_id,
        author_kind,
        visibility,
        body,
    ):
        captured.update(
            application_id=application_id,
            comment_id=comment_id,
            author_kind=author_kind,
            visibility=visibility,
            body=body,
        )
        return 1

    monkeypatch.setattr(comments_mod, "send_comment_notifications", _send)

    aid, cid = uuid4(), uuid4()
    await _deliver_comment_mails(
        _settings(), aid, cid, "principal", "public", "hallo", pool=None
    )
    assert captured["application_id"] == aid
    assert captured["comment_id"] == cid
    assert captured["author_kind"] == "principal"
    assert captured["visibility"] == "public"
    assert captured["body"] == "hallo"


# --- Router-Endpunkte (list_tasks, get_form, erasure) via TestClient ------- #
def _state() -> StateOut:
    return StateOut(
        id=uuid4(), key="draft", label={"de": "E"}, color="#abcdef", editAllowed=True
    )


class _AppsServiceFake:
    def __init__(self) -> None:
        self.session = _FakeMagicSession()
        self.tasks_principal: Principal | None = None
        self.form_for: Any = None

    async def list_tasks(self, principal: Principal) -> list[ApplicationListItem]:
        self.tasks_principal = principal
        return [
            ApplicationListItem(
                id=uuid4(),
                typeId=uuid4(),
                state=_state(),
                createdAt=datetime(2026, 6, 1, tzinfo=UTC),
                updatedAt=datetime(2026, 6, 1, tzinfo=UTC),
            )
        ]

    async def effective_form(self, application_id: Any) -> Any:
        from app.modules.forms.schemas import EffectiveFormOut

        self.form_for = application_id
        return EffectiveFormOut(
            applicationTypeId=uuid4(),
            formVersionId=uuid4(),
            budgetPotId=None,
            sections=[],
        )


@pytest.fixture
def apps_app() -> tuple[FastAPI, _AppsServiceFake]:
    application = create_app()
    svc = _AppsServiceFake()
    application.dependency_overrides[get_applications_service] = lambda: svc
    return application, svc


def test_list_tasks_passes_principal(
    apps_app: tuple[FastAPI, _AppsServiceFake],
) -> None:
    application, svc = apps_app
    application.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="u-task"
    )
    from app.deps import get_current_applicant

    application.dependency_overrides[get_current_applicant] = lambda: None
    client = TestClient(application)
    r = client.get("/api/applications/tasks")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert svc.tasks_principal is not None and svc.tasks_principal.sub == "u-task"


def test_list_tasks_requires_auth_401(
    apps_app: tuple[FastAPI, _AppsServiceFake],
) -> None:
    application, _svc = apps_app
    assert TestClient(application).get("/api/applications/tasks").status_code == 401


def test_get_application_form_principal(
    apps_app: tuple[FastAPI, _AppsServiceFake],
) -> None:
    """``GET /applications/{id}/form`` liefert die gepinnte effektive Form (A/P-Read)."""
    application, svc = apps_app
    application.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="reader", permissions={"application.read"}
    )
    from app.deps import get_current_applicant

    application.dependency_overrides[get_current_applicant] = lambda: None
    client = TestClient(application)
    app_id = uuid4()
    r = client.get(f"/api/applications/{app_id}/form")
    assert r.status_code == 200
    assert str(svc.form_for) == str(app_id)


class _ErasureFake:
    def __init__(self, _session: object) -> None:
        self._session = _session

    async def create(self, *, subject_type: str, application_id: Any, requested_by: Any) -> Any:
        return SimpleNamespace(id=uuid4())


def test_request_erasure_202(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DSGVO-Löschantrag: 202 + Benachrichtigung der Datenschutz-Verantwortlichen."""
    import app.modules.applications.router as ar
    from app.db import get_session
    from app.deps import get_current_applicant

    application = create_app()
    app_id = uuid4()

    async def _fake_session() -> Any:
        yield _FakeMagicSession()

    application.dependency_overrides[get_session] = _fake_session
    application.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="staff", permissions={"application.read"}
    )
    application.dependency_overrides[get_current_applicant] = lambda: None

    monkeypatch.setattr(ar, "ErasureRequestService", _ErasureFake)
    notified: dict[str, Any] = {}

    async def _notify(*, queue, settings, request_id, subject_type):  # noqa: ANN001
        notified["request_id"] = request_id
        notified["subject_type"] = subject_type

    monkeypatch.setattr(ar, "notify_erasure_requested", _notify)
    monkeypatch.setattr(ar, "mail_queue_from_pool", lambda _pool: None)

    client = TestClient(application)
    r = client.post(f"/api/applications/{app_id}/erasure-request")
    assert r.status_code == 202
    # Background-Task lief synchron im TestClient → Benachrichtigung wurde ausgelöst.
    assert notified.get("subject_type") == "applicant"


def test_request_erasure_requires_access_401() -> None:
    """Ohne Identität (kein Principal/Applicant) → 401 (require_app_read)."""
    from app.db import get_session

    application = create_app()

    async def _fake_session() -> Any:
        yield _FakeMagicSession()

    application.dependency_overrides[get_session] = _fake_session
    client = TestClient(application)
    r = client.post(f"/api/applications/{uuid4()}/erasure-request")
    assert r.status_code == 401


class _CreateServiceFake:
    """Service-Fake für ``POST /applications`` (in-Handler-Validierungszweige)."""

    def __init__(self) -> None:
        self.created = False

    async def create(self, payload: Any, *, actor: str = "applicant") -> Any:
        self.created = True
        return SimpleNamespace(id=uuid4()), str(payload.applicant_email)


def _create_app_for_post() -> tuple[FastAPI, _CreateServiceFake]:
    from app.deps import get_current_applicant

    application = create_app()
    svc = _CreateServiceFake()
    application.dependency_overrides[get_applications_service] = lambda: svc

    async def _no_mail(settings, email, application_id, pool):  # noqa: ANN001, ANN202
        return None

    application.dependency_overrides[get_magic_link_sender] = lambda: _no_mail
    application.dependency_overrides[get_current_applicant] = lambda: None
    return application, svc


def test_create_application_in_handler_payload_cap_413() -> None:
    """In-Handler-Schranke (serialisierte ``data``) → 413, auch wenn die
    Content-Length-Dependency den Body durchgelassen hätte."""
    from app.shared.antiabuse import enforce_application_payload_limit

    application, svc = _create_app_for_post()
    # Content-Length-Dependency zum No-op machen → der Handler-Check (Zeile 162-165)
    # ist die maßgebliche Schranke.
    application.dependency_overrides[enforce_application_payload_limit] = lambda: None
    application.dependency_overrides[get_current_principal] = lambda: None
    client = TestClient(application)
    body = {
        "typeId": str(uuid4()),
        "data": {"blob": "x" * 70_000},  # serialisiert > max_application_payload_bytes
        "applicantEmail": "a@example.org",
        "lang": "de",
    }
    r = client.post("/api/applications", json=body)
    assert r.status_code == 413
    assert svc.created is False  # nie an den Service durchgereicht


def test_create_application_missing_email_422() -> None:
    """Anonym + ohne ``applicantEmail`` + ohne Account → ValidationProblem (422)."""
    application, svc = _create_app_for_post()
    application.dependency_overrides[get_current_principal] = lambda: None
    client = TestClient(application)
    body = {"typeId": str(uuid4()), "data": {"title": "x"}, "lang": "de"}
    r = client.post("/api/applications", json=body)
    assert r.status_code == 422
    assert svc.created is False


def test_create_application_derives_name_from_principal_only() -> None:
    """Eingeloggt mit ``applicantEmail`` aber ohne Name → Name aus dem Account (Zeile 180-181)."""
    application, svc = _create_app_for_post()
    application.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="u-9", email="acct@example.org", display_name="Account Name"
    )
    client = TestClient(application)
    body = {
        "typeId": str(uuid4()),
        "data": {"title": "x"},
        "applicantEmail": "explicit@example.org",
        "lang": "de",
    }
    r = client.post("/api/applications", json=body)
    assert r.status_code == 201
    assert svc.created is True


# Defensive: vermeidet ungenutzte Importe, falls Linter streng ist.
_ = (column, GremiumOut, contextlib)
