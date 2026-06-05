"""TDD: Auth-Orchestrierung (security.md §1/§2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.applications.models import Application, MagicLink
from app.modules.auth import service, tokens
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oidc import OidcClaims
from app.modules.flow.models import State
from app.settings import Settings, load_settings
from app.shared.errors import GoneError
from tests.auth_fakes import fake_session, result

NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def _settings() -> Settings:
    return load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="sess-secret",
        magic_link_secret="ml-pepper",
        public_base_url="https://antrag.example",
    )


def _app(state_id: object | None = None) -> Application:
    app = Application()
    app.id = "aid-1"  # type: ignore[assignment]
    app.current_state_id = state_id  # type: ignore[assignment]
    return app


# --------------------------------------------------------------------------- #
# request_magic_link
# --------------------------------------------------------------------------- #
async def test_request_magic_link_no_match_is_silent() -> None:
    settings = _settings()
    db = fake_session(result())  # kein Antrag
    sent: list[tuple[str, str]] = []
    await service.request_magic_link(
        db, settings, email="x@y.de", deliver=lambda e, link: sent.append((e, link))
    )
    assert sent == []
    assert db.added == []


async def test_request_magic_link_edit_scope_no_state() -> None:
    settings = _settings()
    db = fake_session(result(_app()))  # current_state_id None → edit
    sent: list[tuple[str, str]] = []
    await service.request_magic_link(
        db, settings, email="x@y.de", deliver=lambda e, link: sent.append((e, link))
    )
    assert len(db.added) == 1
    link = sent[0][1]
    assert "/antrag/aid-1?t=" in link
    assert db.added[0].scope == "edit"
    assert db.added[0].single_use is False


async def test_request_magic_link_view_scope_when_locked() -> None:
    settings = _settings()
    locked = State()
    locked.edit_allowed = False  # type: ignore[assignment]
    db = fake_session(result(_app(state_id="s1")), result(locked))
    sent: list[tuple[str, str]] = []
    await service.request_magic_link(
        db, settings, email="x@y.de", application_id="aid-1",
        deliver=lambda e, link: sent.append((e, link)),
    )
    assert db.added[0].scope == "view"
    assert db.added[0].single_use is True


async def test_request_magic_link_default_deliver_runs() -> None:
    settings = _settings()
    db = fake_session(result(_app()))
    # Ohne `deliver` → _default_deliver läuft (loggt nur Empfänger-Domain, kein Token).
    await service.request_magic_link(db, settings, email="x@y.de")
    assert len(db.added) == 1


async def test_request_magic_link_edit_scope_when_open_state() -> None:
    settings = _settings()
    open_state = State()
    open_state.edit_allowed = True  # type: ignore[assignment]
    db = fake_session(result(_app(state_id="s1")), result(open_state))
    await service.request_magic_link(db, settings, email="x@y.de", deliver=lambda e, link: None)
    assert db.added[0].scope == "edit"


# --------------------------------------------------------------------------- #
# verify_magic_link
# --------------------------------------------------------------------------- #
def _link(token: str, settings: Settings, **kw: object) -> MagicLink:
    row = MagicLink(
        application_id="aid-1",
        token_hash=tokens.hash_token(token, settings.magic_link_secret),
        scope=kw.get("scope", "edit"),  # type: ignore[arg-type]
        expires_at=kw.get("expires_at", NOW + timedelta(days=1)),  # type: ignore[arg-type]
        single_use=kw.get("single_use", False),  # type: ignore[arg-type]
    )
    row.used_at = kw.get("used_at")  # type: ignore[assignment]
    return row


async def test_verify_magic_link_not_found() -> None:
    settings = _settings()
    db = fake_session(result())
    with pytest.raises(GoneError):
        await service.verify_magic_link(db, settings, token="tok")


async def test_verify_magic_link_hash_mismatch() -> None:
    settings = _settings()
    bad = MagicLink(application_id="aid-1", token_hash=b"\x00" * 32, scope="edit",
                    expires_at=NOW + timedelta(days=1), single_use=False)
    db = fake_session(result(bad))
    with pytest.raises(GoneError):
        await service.verify_magic_link(db, settings, token="tok")


async def test_verify_magic_link_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr(service, "_now", lambda: NOW)
    row = _link("tok", settings, expires_at=NOW - timedelta(seconds=1))
    db = fake_session(result(row))
    with pytest.raises(GoneError):
        await service.verify_magic_link(db, settings, token="tok")


async def test_verify_magic_link_already_used(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr(service, "_now", lambda: NOW)
    row = _link("tok", settings, single_use=True, used_at=NOW)
    db = fake_session(result(row))
    with pytest.raises(GoneError):
        await service.verify_magic_link(db, settings, token="tok")


async def test_verify_magic_link_single_use_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr(service, "_now", lambda: NOW)
    row = _link("tok", settings, scope="view", single_use=True)
    db = fake_session(result(row))
    app_id, scope, token = await service.verify_magic_link(db, settings, token="tok")
    assert app_id == "aid-1"
    assert scope == "view"
    assert row.used_at == NOW  # single_use markiert
    assert token  # signierter Applicant-Token


async def test_verify_magic_link_edit_not_marked_used(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr(service, "_now", lambda: NOW)
    row = _link("tok", settings, scope="edit", single_use=False)
    db = fake_session(result(row))
    _, scope, _ = await service.verify_magic_link(db, settings, token="tok")
    assert scope == "edit"
    assert row.used_at is None


# --------------------------------------------------------------------------- #
# OIDC
# --------------------------------------------------------------------------- #
async def test_upsert_principal_new() -> None:
    db = fake_session(result())  # kein bestehender Principal
    claims = OidcClaims(sub="s1", email="e@x.de", name="N", groups=["g"])
    row = await service.upsert_principal(db, claims)
    assert row.sub == "s1"
    assert row.email == "e@x.de"
    assert row.oidc_groups == ["g"]
    assert len(db.added) == 1


async def test_upsert_principal_existing() -> None:
    existing = PrincipalRow(sub="s1")
    db = fake_session(result(existing))
    claims = OidcClaims(sub="s1", email="new@x.de", name="New", groups=[])
    row = await service.upsert_principal(db, claims)
    assert row is existing
    assert row.email == "new@x.de"
    assert db.added == []  # kein Insert


async def test_oidc_callback_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()

    async def fake_exchange(s: Settings, *, code: str, verifier: str) -> dict[str, str]:
        return {"id_token": "idt", "refresh_token": "rt"}

    async def fake_verify(s: Settings, *, id_token: str, nonce: str) -> OidcClaims:
        return OidcClaims(sub="s1", email="e@x.de", name="N", groups=["g"])

    monkeypatch.setattr(service.oidc, "exchange_code", fake_exchange)
    monkeypatch.setattr(service.oidc, "verify_id_token", fake_verify)
    db = fake_session(result())  # upsert: kein bestehender Principal
    cookie, row = await service.oidc_callback(
        db, settings, code="c", verifier="v", nonce="n"
    )
    assert cookie  # signiertes sid-Cookie
    assert row.sub == "s1"
    # 1 Principal-Insert + 1 AuthSession-Insert
    assert len(db.added) == 2
