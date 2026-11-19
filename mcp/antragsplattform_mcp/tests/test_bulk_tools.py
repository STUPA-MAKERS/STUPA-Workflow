"""Tests for the bulk tools and the new-version tool (specs 001700-001703, 001720)."""

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


def test_new_version_posts_without_a_body(fake_api: _FakeApi) -> None:
    asyncio.run(applications.create_application_new_version("a1"))
    assert fake_api.calls == [("/applications/a1/new-version", None)]


def test_bulk_tools_send_the_ids(fake_api: _FakeApi) -> None:
    asyncio.run(applications.list_bulk_transitions(["a1", "a2"]))
    asyncio.run(applications.fire_bulk_transition(["a1"], "s1"))
    asyncio.run(applications.fire_bulk_transition(["a1"], "s1", note="Runde"))
    asyncio.run(applications.send_bulk_message(["a1", "a2"], "Hallo"))
    assert fake_api.calls == [
        ("/bulk/applications/transitions", {"applicationIds": ["a1", "a2"]}),
        ("/bulk/applications/transition", {"applicationIds": ["a1"], "toStateId": "s1"}),
        (
            "/bulk/applications/transition",
            {"applicationIds": ["a1"], "toStateId": "s1", "note": "Runde"},
        ),
        ("/bulk/applications/comments", {"applicationIds": ["a1", "a2"], "body": "Hallo"}),
    ]
