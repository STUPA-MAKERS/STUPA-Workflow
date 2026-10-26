"""Tests for the UI text and UI language tools.

Each tool must call the correct `/admin/translations` route with the correct method
and body.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from antragsplattform_mcp import schemas as S
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

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("POST", path, **kw)

    async def patch(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("PATCH", path, **kw)

    async def put(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("PUT", path, **kw)

    async def delete(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._call("DELETE", path, **kw)


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_translation_tools_are_registered() -> None:
    server = FastMCP("test")
    register_all(server)
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    for present in (
        "list_ui_languages",
        "create_ui_language",
        "update_ui_language",
        "delete_ui_language",
        "get_ui_texts",
        "set_ui_texts",
    ):
        assert present in names


def test_language_routes(fake_api: _FakeApi) -> None:
    asyncio.run(admin.list_ui_languages())
    asyncio.run(admin.create_ui_language(S.UiLanguageCreate(code="fr", name="Français")))
    asyncio.run(admin.update_ui_language("fr", S.UiLanguageUpdate(active=True)))
    asyncio.run(admin.delete_ui_language("fr"))
    assert fake_api.calls == [
        ("GET", "/admin/translations/languages", None),
        (
            "POST",
            "/admin/translations/languages",
            {"code": "fr", "name": "Français", "active": False},
        ),
        ("PATCH", "/admin/translations/languages/fr", {"active": True}),
        ("DELETE", "/admin/translations/languages/fr", None),
    ]


def test_text_routes(fake_api: _FakeApi) -> None:
    asyncio.run(admin.get_ui_texts("en"))
    asyncio.run(admin.set_ui_texts("en", {"a.b": "Text", "c.d": None}))
    assert fake_api.calls == [
        ("GET", "/admin/translations/texts/en", None),
        ("PUT", "/admin/translations/texts/en", {"changes": {"a.b": "Text", "c.d": None}}),
    ]
