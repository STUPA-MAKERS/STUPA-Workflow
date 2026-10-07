"""Tests for the public-protocol options of the gremium and protocol tools."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.tools import _common, admin, meetings


class _FakeApi:
    """Record each POST and PATCH and answer with an empty object."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("POST", path, kw.get("json")))
        return {}

    async def patch(self, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("PATCH", path, kw.get("json")))
        return {}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_create_gremium_sends_protocols_public(fake_api: _FakeApi) -> None:
    asyncio.run(
        admin.create_gremium(S.GremiumCreate(name="AStA", slug="asta", protocolsPublic=True))
    )
    assert fake_api.calls[0][2]["protocolsPublic"] is True


def test_update_gremium_sends_only_the_flag(fake_api: _FakeApi) -> None:
    asyncio.run(admin.update_gremium("g1", S.GremiumUpdate(protocolsPublic=True)))
    assert fake_api.calls == [("PATCH", "/admin/gremien/g1", {"protocolsPublic": True})]


def test_finalize_passes_the_withhold_option(fake_api: _FakeApi) -> None:
    asyncio.run(meetings.finalize_protocol("p1"))
    asyncio.run(meetings.finalize_protocol("p2", public_withheld=True))
    asyncio.run(meetings.finalize_protocol("p3", public_withheld=False))
    assert fake_api.calls == [
        ("POST", "/protocols/p1/finalize", {}),
        ("POST", "/protocols/p2/finalize", {"publicWithheld": True}),
        ("POST", "/protocols/p3/finalize", {"publicWithheld": False}),
    ]


def test_update_protocol_sends_the_set_fields(fake_api: _FakeApi) -> None:
    asyncio.run(meetings.update_protocol("p1", markdown="Text"))
    asyncio.run(meetings.update_protocol("p1", public_withheld=True))
    asyncio.run(meetings.update_protocol("p1", markdown="Text", public_withheld=False))
    assert [call[2] for call in fake_api.calls] == [
        {"markdown": "Text"},
        {"publicWithheld": True},
        {"markdown": "Text", "publicWithheld": False},
    ]
