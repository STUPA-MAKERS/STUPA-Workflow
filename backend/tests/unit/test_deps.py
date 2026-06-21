"""TDD: Auth-Dependencies (api.md §1, security.md §1/§2) — reale Auflösung (T-10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import deps
from app.deps import (
    Applicant,
    Principal,
    get_current_applicant,
    get_current_principal,
    require_applicant,
    require_group,
    require_principal,
)
from app.modules.auth import sessions
from app.modules.auth.models import ApplicantSession, AuthSession
from app.settings import Settings, load_settings
from app.shared.errors import ForbiddenError, UnauthorizedError
from tests._support.auth_fakes import fake_session, result

SECRET = "deps-secret-0123456"


def _settings() -> Settings:
    return load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret=SECRET,
        magic_link_secret="magic-link-secret-0",
    )


def _request(*, cookies: dict[str, str] | None = None,
             headers: dict[str, str] | None = None, query: str = "") -> Request:
    raw: list[tuple[bytes, bytes]] = []
    if cookies:
        raw.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    for k, v in (headers or {}).items():
        raw.append((k.lower().encode(), v.encode()))
    return Request({"type": "http", "headers": raw, "query_string": query.encode()})


# --------------------------------------------------------------------------- #
# require_principal / require_group / require_applicant (Factory-Logik)
# --------------------------------------------------------------------------- #
def test_require_principal_no_session_unauthorized() -> None:
    with pytest.raises(UnauthorizedError):
        require_principal("application.read")(principal=None)


def test_require_principal_missing_perm_forbidden() -> None:
    p = Principal(sub="u", permissions={"application.read"})
    with pytest.raises(ForbiddenError):
        require_principal("admin.config")(principal=p)


def test_require_principal_ok() -> None:
    p = Principal(sub="u", permissions={"application.read"})
    assert require_principal("application.read")(principal=p) is p


def test_require_group_no_session_unauthorized() -> None:
    with pytest.raises(UnauthorizedError):
        require_group("stupa")(principal=None)


def test_require_group_not_member_forbidden() -> None:
    p = Principal(sub="u", groups={"asta"})
    with pytest.raises(ForbiddenError):
        require_group("stupa")(principal=p)


def test_require_group_ok() -> None:
    p = Principal(sub="u", groups={"stupa"})
    assert require_group("stupa")(principal=p) is p


def test_require_applicant_no_token_unauthorized() -> None:
    with pytest.raises(UnauthorizedError):
        require_applicant("view")(applicant=None)


def test_require_applicant_scope_insufficient_forbidden() -> None:
    a = Applicant(application_id="a1", scope="view")
    with pytest.raises(ForbiddenError):
        require_applicant("edit")(applicant=a)


def test_require_applicant_ok() -> None:
    a = Applicant(application_id="a1", scope="edit")
    assert require_applicant("view")(applicant=a) is a


# --------------------------------------------------------------------------- #
# get_current_applicant (serverseitige Session: signierte opake sid → DB-Zeile)
# --------------------------------------------------------------------------- #
def _applicant_row(
    *, sid: str = "as1", application_id: str = "a1", scope: str = "edit",
    expired: bool = False, revoked: bool = False,
) -> ApplicantSession:
    now = datetime.now(UTC)
    row = ApplicantSession(
        sid=sid,
        application_id=application_id,
        scope=scope,
        expires_at=now - timedelta(seconds=1) if expired else now + timedelta(hours=1),
    )
    if revoked:
        row.revoked_at = now
    return row


def _cookie(sid: str = "as1") -> str:
    return sessions._sign_applicant_sid(SECRET, sid)


async def test_get_current_applicant_bearer() -> None:
    req = _request(headers={"Authorization": f"Bearer {_cookie()}"})
    db = fake_session(result(_applicant_row(application_id="a1", scope="edit")))
    applicant = await get_current_applicant(req, db, _settings())
    assert applicant is not None
    assert applicant.application_id == "a1"
    assert applicant.scope == "edit"


async def test_get_current_applicant_query_param_not_accepted() -> None:
    # `?t=` wird bewusst NICHT mehr akzeptiert (Query-Token-Leak, security.md §1).
    req = _request(query=f"t={_cookie()}")
    assert await get_current_applicant(req, fake_session(), _settings()) is None


async def test_get_current_applicant_cookie() -> None:
    req = _request(cookies={_settings().applicant_cookie_name: _cookie()})
    db = fake_session(result(_applicant_row(application_id="a3")))
    applicant = await get_current_applicant(req, db, _settings())
    assert applicant is not None
    assert applicant.application_id == "a3"


async def test_get_current_applicant_no_token() -> None:
    assert await get_current_applicant(_request(), fake_session(), _settings()) is None


async def test_get_current_applicant_invalid_token() -> None:
    req = _request(headers={"Authorization": "Bearer garbage"})
    assert await get_current_applicant(req, fake_session(), _settings()) is None


async def test_get_current_applicant_forged_secret_no_row() -> None:
    # KERN-REGRESSION (ISSUE_TOKEN): korrekt signierte sid, aber keine DB-Zeile → None.
    req = _request(headers={"Authorization": f"Bearer {_cookie('forged')}"})
    assert await get_current_applicant(req, fake_session(result()), _settings()) is None


async def test_get_current_applicant_revoked() -> None:
    req = _request(headers={"Authorization": f"Bearer {_cookie()}"})
    db = fake_session(result(_applicant_row(revoked=True)))
    assert await get_current_applicant(req, db, _settings()) is None


async def test_get_current_applicant_bad_scope() -> None:
    req = _request(headers={"Authorization": f"Bearer {_cookie()}"})
    db = fake_session(result(_applicant_row(scope="bogus")))
    assert await get_current_applicant(req, db, _settings()) is None


# --------------------------------------------------------------------------- #
# get_current_principal (sessions/rbac gemockt)
# --------------------------------------------------------------------------- #
async def test_get_current_principal_no_cookie() -> None:
    assert await get_current_principal(_request(), fake_session(), _settings()) is None


async def test_get_current_principal_invalid_session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(*a: object, **k: object) -> None:
        return None

    monkeypatch.setattr(deps.sessions, "load_principal_session", _none)
    req = _request(cookies={_settings().session_cookie_name: "x"})
    assert await get_current_principal(req, fake_session(), _settings()) is None


async def test_get_current_principal_orphan_session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sess(*a: object, **k: object) -> AuthSession:
        return AuthSession(sid="s", principal_id="pid")

    monkeypatch.setattr(deps.sessions, "load_principal_session", _sess)
    req = _request(cookies={_settings().session_cookie_name: "x"})
    # Principal-Zeile fehlt → None.
    assert await get_current_principal(req, fake_session(result()), _settings()) is None


async def test_get_current_principal_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sess(*a: object, **k: object) -> AuthSession:
        return AuthSession(sid="s", principal_id="pid")

    async def _resolve(*a: object, **k: object) -> Principal:
        return Principal(sub="u1", permissions={"application.read"})

    monkeypatch.setattr(deps.sessions, "load_principal_session", _sess)
    monkeypatch.setattr(deps.rbac, "resolve_principal", _resolve)
    req = _request(cookies={_settings().session_cookie_name: "x"})
    principal = await get_current_principal(
        req, fake_session(result(SimpleNamespace(active=True))), _settings()
    )
    assert principal is not None
    assert principal.sub == "u1"


async def test_get_current_principal_deactivated(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sess(*a: object, **k: object) -> AuthSession:
        return AuthSession(sid="s", principal_id="pid")

    monkeypatch.setattr(deps.sessions, "load_principal_session", _sess)
    req = _request(cookies={_settings().session_cookie_name: "x"})
    # Deaktivierter Principal (active=False) → keine Auflösung (#30).
    principal = await get_current_principal(
        req, fake_session(result(SimpleNamespace(active=False))), _settings()
    )
    assert principal is None
