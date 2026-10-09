"""Tests for the filters of `list_principals` and the missing revoke tool (F3).

`list_principals` sends the user-list filters in camelCase; a None filter stays off
the wire. "Rechte entziehen" (`/admin/principals/{id}/revoke`) is a web-only action:
no tool calls it.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from antragsplattform_mcp.tools import _common, admin, register_all


class _FakeApi:
    """Record each GET with its query parameters."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def get(self, path: str, **kw: Any) -> list[Any]:
        self.calls.append((path, kw.get("params")))
        return []


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_list_principals_sends_the_filters(fake_api: _FakeApi) -> None:
    asyncio.run(
        admin.list_principals(
            last_login_before="2026-07-01", include_never=True, has_groups=False
        )
    )
    assert fake_api.calls == [
        (
            "/admin/principals",
            {"lastLoginBefore": "2026-07-01", "includeNever": True, "hasGroups": False},
        )
    ]


def test_list_principals_leaves_unset_filters_off(fake_api: _FakeApi) -> None:
    asyncio.run(admin.list_principals(q="kern"))
    assert fake_api.calls == [("/admin/principals", {"q": "kern"})]


def test_no_tool_revokes_rights() -> None:
    server = FastMCP("test")
    register_all(server)
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert not any("revoke_principal" in n or "revoke_access" in n for n in names)
