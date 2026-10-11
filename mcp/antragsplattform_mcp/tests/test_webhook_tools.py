"""Tests for the webhook tools.

Each tool must call the correct `/admin/webhooks` route with the correct method.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from antragsplattform_mcp.tools import _common, admin, register_all


class _FakeApi:
    """Record each call and answer with a fixed body."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def _call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append((method, path, kw.get("json")))
        return {"status": "ok"}

    async def get(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("GET", path, **kw)

    async def delete(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("DELETE", path, **kw)


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_webhook_tools_are_registered() -> None:
    server = FastMCP("test")
    register_all(server)
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    for present in (
        "list_webhooks",
        "create_webhook",
        "update_webhook",
        "delete_webhook",
    ):
        assert present in names


def test_list_webhooks(fake_api: _FakeApi) -> None:
    asyncio.run(admin.list_webhooks())
    assert fake_api.calls == [("GET", "/admin/webhooks", None)]


def test_delete_webhook(fake_api: _FakeApi) -> None:
    asyncio.run(admin.delete_webhook("w1"))
    assert fake_api.calls == [("DELETE", "/admin/webhooks/w1", None)]
