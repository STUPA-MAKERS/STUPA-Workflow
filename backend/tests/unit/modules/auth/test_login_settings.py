"""Login settings: the defaults, the lifetime per client and the audited update."""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.auth import login_settings
from app.modules.auth.login_settings import (
    LoginSettingsService,
    load_login_settings,
    session_days,
)
from app.modules.auth.models import LoginSettings
from tests._support.auth_fakes import fake_session


async def test_load_falls_back_to_the_defaults() -> None:
    row = await load_login_settings(fake_session())
    assert (row.web_session_days, row.pwa_session_days) == (90, 180)


async def test_load_returns_the_stored_row() -> None:
    stored = LoginSettings(id=1, web_session_days=7, pwa_session_days=14)
    assert await load_login_settings(fake_session(gets=[stored])) is stored


def test_session_days_per_client() -> None:
    row = LoginSettings(id=1, web_session_days=7, pwa_session_days=14)
    assert session_days(row, "web") == 7
    assert session_days(row, "pwa") == 14
    assert session_days(row, "other") == 7


async def test_get_creates_the_missing_row() -> None:
    db = fake_session()
    row = await LoginSettingsService(db).get()
    assert db.added == [row]
    assert row.updated_at is not None


async def test_update_writes_audit_and_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = LoginSettings(id=1, web_session_days=90, pwa_session_days=180)
    db = fake_session(gets=[stored])
    refreshed: list[object] = []

    async def _refresh(obj: object) -> None:
        refreshed.append(obj)

    db.refresh = _refresh
    entries: list[dict[str, Any]] = []

    async def _record(_db: object, **kwargs: Any) -> None:
        entries.append(kwargs)

    monkeypatch.setattr(login_settings, "audit_record", _record)
    row = await LoginSettingsService(db).update(
        web_session_days=30, pwa_session_days=365, actor="admin-1"
    )
    assert (row.web_session_days, row.pwa_session_days) == (30, 365)
    assert row.updated_by == "admin-1"
    assert db.committed == 1
    assert refreshed == [row]
    assert entries[0]["target_type"] == "login_settings"
    assert entries[0]["data"] == {
        "webSessionDays": {"from": 90, "to": 30},
        "pwaSessionDays": {"from": 180, "to": 365},
    }
