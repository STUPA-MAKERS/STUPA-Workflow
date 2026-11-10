"""The e-mail login of the applicants, branch by branch without a database.

The integration suite (`tests/integration/modules/auth/test_email_login.py`) proves
the rules against Postgres. This suite covers each branch of `email_login` with the
fake session, because the critical-module gate counts the unit run only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.modules.applications import guest_settings
from app.modules.auth import email_login, sessions, tokens
from app.modules.auth.models import EmailLoginLink
from app.settings import Settings, load_settings
from app.shared.errors import GoneError
from tests._support.auth_fakes import fake_session, result

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
EMAIL = "lena@example.org"


def _settings() -> Settings:
    return load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="sess-secret-0123456",
        magic_link_secret="ml-pepper-0123456",
        public_base_url="https://antrag.example/",
    )


def _link(token: str, settings: Settings) -> EmailLoginLink:
    row = EmailLoginLink(
        email=EMAIL,
        token_hash=tokens.hash_token(token, settings.magic_link_secret),
        expires_at=NOW + timedelta(minutes=30),
    )
    row.id = uuid.uuid4()
    return row


async def test_call_awaits_only_an_awaitable() -> None:
    """A sync callback returns None; an async one is awaited."""
    seen: list[str] = []

    async def deliver() -> None:
        seen.append("async")

    await email_login._call(None)
    await email_login._call(deliver())
    assert seen == ["async"]


async def test_application_ids_are_strings() -> None:
    db = fake_session(result(uuid.UUID(int=1), uuid.UUID(int=2)))
    ids = await email_login.application_ids(db, EMAIL)
    assert ids == frozenset({str(uuid.UUID(int=1)), str(uuid.UUID(int=2))})


async def test_issue_link_stores_the_hash_and_puts_the_token_in_the_fragment() -> None:
    settings = _settings()
    db = fake_session()
    link = await email_login.issue_link(db, settings, email=EMAIL, expires_at=NOW)
    assert link.startswith("https://antrag.example/my-applications#t=")
    (row,) = db.added
    token = link.split("#t=", 1)[1]
    assert row.token_hash == tokens.hash_token(token, settings.magic_link_secret)
    assert row.email == EMAIL
    assert db.flushed == 1


async def test_request_without_an_application_sends_nothing() -> None:
    db = fake_session(result())
    sent: list[str] = []
    await email_login.request_email_login(
        db, _settings(), email=EMAIL, send_link=lambda _e, link: sent.append(link)
    )
    assert sent == []
    assert db.added == []


async def test_request_with_an_application_sends_one_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(email_login, "_now", lambda: NOW)
    db = fake_session(result(uuid.UUID(int=1)))
    sent: list[tuple[str, str]] = []

    async def send(email: str, link: str) -> None:
        sent.append((email, link))

    await email_login.request_email_login(db, _settings(), email=EMAIL, send_link=send)
    ((email, _link_url),) = sent
    assert email == EMAIL
    assert db.added[0].expires_at == NOW + email_login.LINK_TTL


async def test_confirm_link_lives_as_long_as_the_confirmation_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(email_login, "_now", lambda: NOW)

    async def load(_db: Any) -> Any:
        return SimpleNamespace(confirm_ttl_hours=12)

    monkeypatch.setattr(guest_settings, "load_guest_settings", load)
    db = fake_session()
    link = await email_login.issue_confirm_link(db, _settings(), email=EMAIL)
    assert "#t=" in link
    assert db.added[0].expires_at == NOW + timedelta(hours=12)


async def test_assign_without_ids_reads_nothing() -> None:
    db = fake_session(result("unexpected"))
    await email_login.assign_to_accounts(db, [])
    assert await db.scalar(None) == "unexpected"


async def test_assign_gives_each_application_the_first_matching_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Of two rows for one application the first (newest login) wins; one audit each."""
    audits: list[dict[str, Any]] = []

    async def record(_db: Any, **kwargs: Any) -> None:
        audits.append(kwargs)

    monkeypatch.setattr(email_login, "audit_record", record)
    db = fake_session(
        result(
            ("app-1", "p-new", "sub-new"),
            ("app-1", "p-old", "sub-old"),
            ("app-2", "p-2", "s-2"),
        )
    )
    await email_login.assign_to_accounts(db, ["app-1", "app-2"])
    assert [(a["target_id"], a["data"]["principalId"]) for a in audits] == [
        ("app-1", "p-new"),
        ("app-2", "p-2"),
    ]
    assert all(a["actor"] == email_login.OWNER_MATCH_ACTOR for a in audits)


async def test_verify_unknown_token_is_gone() -> None:
    with pytest.raises(GoneError):
        await email_login.verify_email_login(fake_session(result()), _settings(), token="x")


async def test_verify_hash_mismatch_is_gone() -> None:
    settings = _settings()
    row = _link("tok", settings)
    row.token_hash = b"\x00" * 32
    with pytest.raises(GoneError):
        await email_login.verify_email_login(fake_session(result(row)), settings, token="tok")


async def test_verify_used_or_ended_link_is_gone() -> None:
    """The conditional UPDATE matches no row: the link is used or ended."""
    settings = _settings()
    db = fake_session(result(_link("tok", settings)), result())
    with pytest.raises(GoneError):
        await email_login.verify_email_login(db, settings, token="tok")


async def test_verify_confirms_assigns_and_starts_each_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr(email_login, "_now", lambda: NOW)
    assigned: list[list[object]] = []
    started: list[tuple[object, object]] = []
    made: list[dict[str, Any]] = []

    async def assign(_db: Any, ids: Any) -> None:
        assigned.append(list(ids))

    async def create(_db: Any, **kwargs: Any) -> str:
        made.append(kwargs)
        return "sid-1"

    class _Flow:
        def __init__(self, _db: Any, dispatcher: Any = None) -> None:
            self.dispatcher = dispatcher

        async def start_confirmed(self, app_id: object) -> None:
            started.append((app_id, self.dispatcher))

    monkeypatch.setattr(email_login, "assign_to_accounts", assign)
    monkeypatch.setattr(sessions, "create_applicant_session", create)
    monkeypatch.setattr(email_login, "FlowService", _Flow)
    db = fake_session(result(_link("tok", settings)), result(EMAIL), result("a1", "a2"))
    sid = await email_login.verify_email_login(db, settings, token="tok", dispatcher=cast(Any, "d"))
    assert sid == "sid-1"
    assert assigned == [["a1", "a2"]]
    assert started == [("a1", "d"), ("a2", "d")]
    assert made[0]["email"] == EMAIL
    assert made[0]["expires_at"] == NOW + timedelta(hours=settings.applicant_session_ttl_hours)


async def test_resolve_session_reads_the_applications_of_now() -> None:
    db = fake_session(result(uuid.UUID(int=3)))
    applicant = await email_login.resolve_session(db, EMAIL)
    assert applicant.email == EMAIL
    assert applicant.application_ids == {str(uuid.UUID(int=3))}
