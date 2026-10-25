"""TDD: auth orchestration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.applications.models import Application, MagicLink
from app.modules.auth import service, tokens
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oidc import OidcClaims
from app.settings import Settings, load_settings
from app.shared.errors import ForbiddenError, GoneError
from tests._support.auth_fakes import fake_session, result

NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def _settings() -> Settings:
    return load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="sess-secret-0123456",
        magic_link_secret="ml-pepper-0123456",
        public_base_url="https://antrag.example",
    )


def _app(state_id: object | None = None) -> Application:
    app = Application()
    app.id = "aid-1"  # type: ignore[assignment]
    app.current_state_id = state_id  # type: ignore[assignment]
    return app


async def test_request_magic_link_no_match_is_silent() -> None:
    """Send no link and raise nothing when no application matches."""
    settings = _settings()
    db = fake_session(result())
    sent: list[tuple[str, str]] = []
    await service.request_magic_link(
        db, settings, email="x@y.de", deliver=lambda e, link: sent.append((e, link))
    )
    assert sent == []
    assert db.added == []


async def test_request_magic_link_edit_scope_unlimited_by_default() -> None:
    """Issue an edit link without expiry when no settings row exists.

    The token sits in the URL fragment, not in the query.
    """
    settings = _settings()
    db = fake_session(result(_app()))
    sent: list[tuple[str, str]] = []
    await service.request_magic_link(
        db, settings, email="x@y.de", deliver=lambda e, link: sent.append((e, link))
    )
    assert len(db.added) == 1
    link = sent[0][1]
    assert "/antrag/aid-1#t=" in link
    assert db.added[0].scope == "edit"
    assert db.added[0].single_use is False
    assert db.added[0].expires_at is None


async def test_request_magic_link_filters_by_application_id() -> None:
    """With an application id, the lookup also filters on that id."""
    db = fake_session(result(_app()))
    sent: list[tuple[str, str]] = []
    await service.request_magic_link(
        db, _settings(), email="x@y.de", application_id="aid-1",
        deliver=lambda e, link: sent.append((e, link)),
    )
    assert len(sent) == 1
    assert db.added[0].application_id == "aid-1"


async def test_request_magic_link_default_deliver_runs() -> None:
    """Run `_default_deliver` when no `deliver` is given.

    It logs the recipient domain and no token.
    """
    settings = _settings()
    db = fake_session(result(_app()))
    await service.request_magic_link(db, settings, email="x@y.de")
    assert len(db.added) == 1


async def test_request_magic_link_awaits_async_deliver() -> None:
    """The service awaits an async deliver callback (mail enqueue, isawaitable branch)."""
    settings = _settings()
    db = fake_session(result(_app()))
    sent: list[tuple[str, str]] = []

    async def deliver(email: str, link: str) -> None:
        sent.append((email, link))

    await service.request_magic_link(db, settings, email="x@y.de", deliver=deliver)
    assert len(sent) == 1 and "/antrag/aid-1#t=" in sent[0][1]


def _link(token: str, settings: Settings, **kw: object) -> MagicLink:
    row = MagicLink(
        application_id="aid-1",
        token_hash=tokens.hash_token(token, settings.magic_link_secret),
        scope=kw.get("scope", "edit"),
        expires_at=kw.get("expires_at", NOW + timedelta(days=1)),
        single_use=kw.get("single_use", False),
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
    """Atomic redemption: the UPDATE hits 0 rows because the link is used, so 410."""
    settings = _settings()
    monkeypatch.setattr(service, "_now", lambda: NOW)
    row = _link("tok", settings, single_use=True)
    db = fake_session(result(row), result())
    with pytest.raises(GoneError):
        await service.verify_magic_link(db, settings, token="tok")


async def test_verify_magic_link_single_use_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redeem the token when the UPDATE wins and returns the id.

    An old view link opens an edit session too, and the result holds a signed applicant
    token.
    """
    settings = _settings()
    monkeypatch.setattr(service, "_now", lambda: NOW)
    row = _link("tok", settings, scope="view", single_use=True)
    db = fake_session(result(row), result("claimed-id"))
    app_id, scope, token = await service.verify_magic_link(db, settings, token="tok")
    assert app_id == "aid-1"
    assert scope == "edit"
    assert token


async def test_verify_magic_link_edit_not_marked_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run no UPDATE for a link that is not single use."""
    settings = _settings()
    monkeypatch.setattr(service, "_now", lambda: NOW)
    row = _link("tok", settings, scope="edit", single_use=False)
    db = fake_session(result(row))
    _, scope, _ = await service.verify_magic_link(db, settings, token="tok")
    assert scope == "edit"


class _FakeFlow:
    """Stand-in for `FlowService` that records `start_confirmed` calls."""

    started: list[tuple[object, object]] = []

    def __init__(self, _db: object, dispatcher: object = None) -> None:
        self.dispatcher = dispatcher

    async def start_confirmed(self, application_id: object) -> None:
        _FakeFlow.started.append((application_id, self.dispatcher))


async def test_verify_magic_link_first_confirmation_starts_the_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verify that confirms the email starts the resting flow.

    The confirmation UPDATE matches the row and returns its id.
    """
    settings = _settings()
    monkeypatch.setattr(service, "_now", lambda: NOW)
    monkeypatch.setattr(service, "FlowService", _FakeFlow)
    _FakeFlow.started = []
    row = _link("tok", settings, scope="edit", single_use=False)
    dispatcher = object()
    db = fake_session(result(row), result("aid-1"))
    await service.verify_magic_link(db, settings, token="tok", dispatcher=dispatcher)  # pyright: ignore[reportArgumentType]
    assert _FakeFlow.started == [("aid-1", dispatcher)]


async def test_verify_magic_link_second_click_starts_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The email is already confirmed: no second start, so no second mail.

    The UPDATE matches no row.
    """
    settings = _settings()
    monkeypatch.setattr(service, "_now", lambda: NOW)
    monkeypatch.setattr(service, "FlowService", _FakeFlow)
    _FakeFlow.started = []
    row = _link("tok", settings, scope="edit", single_use=False)
    db = fake_session(result(row), result())
    await service.verify_magic_link(db, settings, token="tok")
    assert _FakeFlow.started == []


class _FailingDispatcher:
    async def dispatch(self, _actions: object) -> None:
        raise RuntimeError("mail queue down")


async def test_verify_magic_link_survives_a_failed_flow_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed flow start after the commit does not fail the verify.

    The confirmation and the applicant session are already committed. The verify must
    still return the session token, else the cookie is lost and a second click starts
    nothing.

    The execute calls follow this order: the magic link, the single-use claim, the
    confirmation UPDATE, the UPDATE that expires the older links,
    `FlowService._load_app` and the latest status event of the task mail.
    """
    from app.modules.flow.service import FlowService

    settings = _settings()
    monkeypatch.setattr(service, "_now", lambda: NOW)

    async def _advance(_self: object, _application_id: object, _principal: object) -> None:
        return None

    monkeypatch.setattr(FlowService, "auto_advance", _advance)
    row = _link("tok", settings, scope="view", single_use=True)
    app = _app(state_id="s1")
    app.email_confirmed_at = NOW
    db = fake_session(
        result(row),
        result("claimed-id"),
        result("aid-1"),
        result(),
        result(app),
        result("event-1"),
    )
    app_id, scope, token = await service.verify_magic_link(
        db, settings, token="tok", dispatcher=_FailingDispatcher()  # pyright: ignore[reportArgumentType]
    )
    assert (app_id, scope) == ("aid-1", "edit")
    assert token
    assert db.rolled_back == 1


async def test_upsert_principal_new() -> None:
    """Insert a new principal when no principal exists for the sub."""
    db = fake_session(result())
    claims = OidcClaims(sub="s1", email="e@x.de", name="N", groups=["g"])
    row = await service.upsert_principal(db, claims)
    assert row.sub == "s1"
    assert row.email == "e@x.de"
    assert row.oidc_groups == ["g"]
    assert len(db.added) == 1


async def test_upsert_principal_existing() -> None:
    """Update an existing principal without an insert."""
    existing = PrincipalRow(sub="s1")
    db = fake_session(result(existing))
    claims = OidcClaims(sub="s1", email="new@x.de", name="New", groups=[])
    row = await service.upsert_principal(db, claims)
    assert row is existing
    assert row.email == "new@x.de"
    assert db.added == []


async def test_upsert_principal_merged_is_refused() -> None:
    """A merged (old) account never logs in again, and the refusal changes nothing."""
    existing = PrincipalRow(sub="old", email="old@x.de", display_name="Alt")
    existing.merged_into = uuid.uuid4()
    db = fake_session(result(existing))
    claims = OidcClaims(sub="old", email="new@x.de", name="New", groups=["g"])
    with pytest.raises(ForbiddenError) as exc:
        await service.upsert_principal(db, claims)
    assert exc.value.code == "account_merged"
    assert existing.email == "old@x.de"
    assert existing.oidc_groups is None
    assert db.added == []
    assert db.flushed == 0


async def test_oidc_callback_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return a signed sid cookie for a new principal.

    The upsert finds no principal. The callback adds one principal insert, one
    AuthSession insert and one LOGIN audit entry. The audit entry holds only the method:
    no IP address, no user agent and no e-mail.
    """
    settings = _settings()

    async def fake_exchange(s: Settings, *, code: str, verifier: str) -> dict[str, str]:
        return {"id_token": "idt", "refresh_token": "rt"}

    async def fake_verify(s: Settings, *, id_token: str, nonce: str) -> OidcClaims:
        return OidcClaims(sub="s1", email="e@x.de", name="N", groups=["g"])

    monkeypatch.setattr(service.oidc, "exchange_code", fake_exchange)
    monkeypatch.setattr(service.oidc, "verify_id_token", fake_verify)
    db = fake_session(result())
    cookie, row = await service.oidc_callback(
        db, settings, code="c", verifier="v", nonce="n"
    )
    assert cookie
    assert row.sub == "s1"
    assert len(db.added) == 3
    entry = db.added[-1]
    assert entry.action == "login"
    assert entry.actor == "s1"
    assert entry.target_type == "principal"
    assert entry.data == {"method": "oidc"}
