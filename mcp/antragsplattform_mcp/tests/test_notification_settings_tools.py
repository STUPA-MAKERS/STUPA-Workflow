"""Tests for the notification settings tools: they call the real backend route."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.tools import _common, admin


class _FakeApi:
    """Record each call and answer with a canned body."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def get(self, path: str, **_kw: Any) -> Any:
        self.calls.append(("GET", path, None))
        return {"taskReminderEnabled": True}

    async def put(self, path: str, **kw: Any) -> Any:
        self.calls.append(("PUT", path, kw.get("json")))
        return {"taskReminderEnabled": False}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_get_notification_settings_reads_the_admin_route(fake_api: _FakeApi) -> None:
    asyncio.run(admin.get_notification_settings())
    assert fake_api.calls == [("GET", "/admin/notification-settings", None)]


def test_update_notification_settings_sends_only_the_set_fields(
    fake_api: _FakeApi,
) -> None:
    patch = S.NotificationSettingsUpdate(taskReminderEnabled=False)
    asyncio.run(admin.update_notification_settings(patch))
    assert fake_api.calls == [
        ("PUT", "/admin/notification-settings", {"taskReminderEnabled": False})
    ]
