"""Magic links without a fixed scope (Z1, O3, O4, F5).

A new link always has the scope `edit`, can be used more than once, and gets its
lifetime from `guest_application_settings.link_ttl_days` (NULL = no expiry). The
verify accepts a link without an expiry, opens an edit session for any link, and
expires the older links of the same application.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.sql.dml import Update

from app.modules.applications.models import (
    Application,
    GuestApplicationSettings,
    MagicLink,
)
from app.modules.auth import service, tokens
from app.settings import Settings, load_settings
from tests._support.auth_fakes import FakeResult, FakeSession, result

NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def _settings() -> Settings:
    return load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="sess-secret-0123456",
        magic_link_secret="ml-pepper-0123456",
        public_base_url="https://antrag.example",
    )


def _session(results: list[FakeResult], gets: list[Any] | None = None) -> Any:
    """Return a `_RecordingSession` typed as `Any`, so it passes as an `AsyncSession`."""
    return _RecordingSession(results, gets)


def _app() -> Application:
    app = Application()
    app.id = "aid-1"  # type: ignore[assignment]
    app.current_state_id = "locked-state"  # type: ignore[assignment]
    return app


class _RecordingSession(FakeSession):
    """A fake session that keeps every executed statement."""

    def __init__(self, results: list[FakeResult], gets: list[Any] | None = None) -> None:
        super().__init__(results, gets=gets or [])
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> FakeResult:
        self.statements.append(stmt)
        return await super().execute(stmt)


async def test_request_writes_an_edit_link_with_the_configured_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`link_ttl_days` sets the expiry. A locked state does not change the scope."""
    monkeypatch.setattr(service, "_now", lambda: NOW)
    cfg = GuestApplicationSettings(id=1, confirm_ttl_hours=12, link_ttl_days=30)
    db = _session([result(_app())], gets=[cfg])
    await service.request_magic_link(db, _settings(), email="x@y.de", deliver=lambda _e, _l: None)
    link = db.added[0]
    assert isinstance(link, MagicLink)
    assert link.scope == "edit"
    assert link.single_use is False
    assert link.expires_at == NOW + timedelta(days=30)
    # The request reads no state and expires no other link (only the lookup runs).
    assert len(db.statements) == 1


async def test_request_writes_an_unlimited_link_when_the_ttl_is_null() -> None:
    cfg = GuestApplicationSettings(id=1, confirm_ttl_hours=12, link_ttl_days=None)
    db = _session([result(_app())], gets=[cfg])
    await service.request_magic_link(db, _settings(), email="x@y.de", deliver=lambda _e, _l: None)
    assert db.added[0].expires_at is None


def _link(settings: Settings, *, expires_at: datetime | None) -> MagicLink:
    row = MagicLink(
        application_id="aid-1",
        token_hash=tokens.hash_token("tok", settings.magic_link_secret),
        scope="edit",
        expires_at=expires_at,
        single_use=False,
    )
    row.id = "link-1"  # type: ignore[assignment]
    row.created_at = NOW - timedelta(days=3)
    return row


async def test_verify_accepts_a_link_without_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    """`expires_at` NULL is valid. Before Z1 the compare raised a TypeError (500)."""
    monkeypatch.setattr(service, "_now", lambda: NOW)
    settings = _settings()
    db = _session([result(_link(settings, expires_at=None))])
    app_id, scope, token = await service.verify_magic_link(db, settings, token="tok")
    assert (app_id, scope) == ("aid-1", "edit")
    assert token


async def test_verify_expires_the_older_links_of_the_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The redeem sets `expires_at = now` on the older, still valid links (O4)."""
    monkeypatch.setattr(service, "_now", lambda: NOW)
    settings = _settings()
    db = _session([result(_link(settings, expires_at=None))])
    await service.verify_magic_link(db, settings, token="tok")
    updates = [s for s in db.statements if isinstance(s, Update)]
    expire = [u for u in updates if getattr(u.table, "name", None) == "magic_link"]
    assert len(expire) == 1
    sql = str(expire[0].compile())
    assert "magic_link.application_id" in sql
    assert "magic_link.id !=" in sql
    assert "magic_link.created_at <=" in sql
    assert "magic_link.expires_at IS NULL" in sql
    params = expire[0].compile().params
    assert params["expires_at"] == NOW
