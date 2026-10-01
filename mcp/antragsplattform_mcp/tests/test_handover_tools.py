"""Tests for the handover tools `protokollant_handover` and `cancel_protokollant_handover`."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp.tools import _common, meetings


class _FakeApi:
    """Record each POST and DELETE and answer with an empty meeting."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("POST", path, kw.get("json")))
        return {}

    async def delete(self, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("DELETE", path, kw.get("json")))
        return {}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_handover_defaults_to_now(fake_api: _FakeApi) -> None:
    asyncio.run(meetings.protokollant_handover("m1", "p1"))
    assert fake_api.calls == [
        ("POST", "/meetings/m1/protokollant-handover", {"principalId": "p1", "mode": "now"})
    ]


def test_handover_next_item(fake_api: _FakeApi) -> None:
    asyncio.run(meetings.protokollant_handover("m1", "p1", mode="next_item"))
    assert fake_api.calls[0][2] == {"principalId": "p1", "mode": "next_item"}


def test_cancel_handover(fake_api: _FakeApi) -> None:
    asyncio.run(meetings.cancel_protokollant_handover("m1"))
    assert fake_api.calls == [("DELETE", "/meetings/m1/protokollant-handover", None)]
