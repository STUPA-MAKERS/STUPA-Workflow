"""Tests for the `list_invoices` tool and its segment filter (FE10c).

`booked` keeps the invoices with (True) or without (False) a booking. False is a
value and goes on the wire; None stays off it.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp.tools import _common, finance


class _FakeApi:
    """Record each GET and answer with an empty page."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def get(self, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append((path, kw.get("params")))
        return {"items": [], "total": 0, "counts": {}}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_list_invoices_sends_the_inbox_segment(fake_api: _FakeApi) -> None:
    asyncio.run(finance.list_invoices(status="open", booked=False))
    assert fake_api.calls == [
        ("/invoices", {"status": "open", "booked": False, "limit": 50, "offset": 0})
    ]


def test_list_invoices_leaves_booked_off_without_a_value(fake_api: _FakeApi) -> None:
    asyncio.run(finance.list_invoices(q="acme"))
    assert fake_api.calls[0][1].get("booked") is None
