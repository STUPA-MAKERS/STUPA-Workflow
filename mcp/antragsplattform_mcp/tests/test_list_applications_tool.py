"""Tests for the `list_applications` tool and its state filter (A4).

The tool sends `state` as a list, so the API gets one repeated `state` parameter
per id. A single id stays possible.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp.tools import _common, applications


class _FakeApi:
    """Record each GET and answer with an empty page."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def get(self, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append((path, kw.get("params")))
        return {"items": [], "total": 0}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_list_applications_with_state_list(fake_api: _FakeApi) -> None:
    asyncio.run(applications.list_applications(state=["s1", "s2"], limit=10))
    assert fake_api.calls == [("/applications", {"state": ["s1", "s2"], "limit": 10})]


def test_list_applications_with_one_state(fake_api: _FakeApi) -> None:
    asyncio.run(applications.list_applications(state="s1"))
    assert fake_api.calls == [("/applications", {"state": ["s1"]})]


def test_list_applications_without_state(fake_api: _FakeApi) -> None:
    asyncio.run(applications.list_applications(state=[]))
    assert fake_api.calls == [("/applications", {})]
