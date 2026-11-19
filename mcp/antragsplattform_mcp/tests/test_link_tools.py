"""§F/collaboration/links/001409: the link tools send the requests of ``/links``."""

from __future__ import annotations

import asyncio

import pytest

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.tests.test_todo_card_parts import _FakeApi
from antragsplattform_mcp.tools import _common, links


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_link_tools_list_add_remove_search_and_view(fake_api: _FakeApi) -> None:
    """Two elements of any kinds link; the link has one id for both ends."""
    asyncio.run(links.link_list("application", "a1"))
    asyncio.run(
        links.link_add(
            S.LinkEndIn(kind="application", id="a1"), S.LinkEndIn(kind="invoice", id="i1")
        )
    )
    asyncio.run(links.link_remove("k1"))
    asyncio.run(links.link_targets("Plak", exclude_kind="application", exclude_id="a1"))
    asyncio.run(links.link_targets(kind="todo"))
    asyncio.run(links.link_view("k1"))
    assert fake_api.calls == [
        ("GET", "/links", {"kind": "application", "id": "a1"}),
        (
            "POST",
            "/links",
            {"a": {"kind": "application", "id": "a1"}, "b": {"kind": "invoice", "id": "i1"}},
        ),
        ("DELETE", "/links/k1", None),
        (
            "GET",
            "/links/targets",
            {"q": "Plak", "kind": "all", "excludeKind": "application", "excludeId": "a1"},
        ),
        ("GET", "/links/targets", {"q": "", "kind": "todo"}),
        ("GET", "/links/k1/view", None),
    ]
