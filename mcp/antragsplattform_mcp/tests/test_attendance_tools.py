"""Tests for the attendance tools `set_attendance` and `reset_attendance`.

`set_attendance` sends `note` only when the caller sets it, so the server keeps
the stored reason otherwise. `reset_attendance` deletes the record.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp.tools import _common, meetings


class _FakeApi:
    """Record each PUT and DELETE and answer with an empty roster."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def put(self, path: str, **kw: Any) -> list[Any]:
        self.calls.append(("PUT", path, kw.get("json")))
        return []

    async def delete(self, path: str, **kw: Any) -> list[Any]:
        self.calls.append(("DELETE", path, kw.get("json")))
        return []


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_set_attendance_without_note(fake_api: _FakeApi) -> None:
    asyncio.run(meetings.set_attendance("m1", "p1", "absent"))
    assert fake_api.calls == [
        ("PUT", "/meetings/m1/attendance/p1", {"status": "absent"})
    ]


def test_set_attendance_with_note(fake_api: _FakeApi) -> None:
    asyncio.run(meetings.set_attendance("m1", "p1", "excused", note="ill"))
    assert fake_api.calls == [
        ("PUT", "/meetings/m1/attendance/p1", {"status": "excused", "note": "ill"})
    ]


def test_reset_attendance(fake_api: _FakeApi) -> None:
    asyncio.run(meetings.reset_attendance("m1", "p1"))
    assert fake_api.calls == [("DELETE", "/meetings/m1/attendance/p1", None)]
