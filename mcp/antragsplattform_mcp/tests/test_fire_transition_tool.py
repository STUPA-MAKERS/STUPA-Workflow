"""Tests for the `fire_transition` tool and its agenda arguments.

A transition with `addsToAgenda` can name the meeting for its agenda item. The tool
sends `meetingId` and `nonPublic` only when the caller sets them.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp.tools import _common, applications


class _FakeApi:
    """Record each POST and answer with a fixed body."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append((path, kw.get("json")))
        return {"status": "ok"}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_fire_transition_without_meeting(fake_api: _FakeApi) -> None:
    asyncio.run(applications.fire_transition("a1", "t1", note="ok"))
    assert fake_api.calls == [
        ("/applications/a1/transition", {"transitionId": "t1", "note": "ok"})
    ]


def test_fire_transition_with_meeting(fake_api: _FakeApi) -> None:
    asyncio.run(
        applications.fire_transition("a1", "t1", meeting_id="m1", non_public=True)
    )
    assert fake_api.calls == [
        (
            "/applications/a1/transition",
            {"transitionId": "t1", "meetingId": "m1", "nonPublic": True},
        )
    ]


def test_fire_transition_with_decision(fake_api: _FakeApi) -> None:
    asyncio.run(
        applications.fire_transition("a1", "t1", approved_amount="800.00", conditions=["A"])
    )
    assert fake_api.calls == [
        (
            "/applications/a1/transition",
            {
                "transitionId": "t1",
                "decision": {"approvedAmount": "800.00", "conditions": ["A"]},
            },
        )
    ]


def test_fire_transition_with_conditions_only(fake_api: _FakeApi) -> None:
    asyncio.run(applications.fire_transition("a1", "t1", conditions=["A"]))
    assert fake_api.calls[0][1]["decision"] == {"conditions": ["A"]}
