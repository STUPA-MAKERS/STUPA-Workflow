"""§F/integrations/mcp/003102: the event tool reads the pretix and Mollie sums, nothing more."""

from __future__ import annotations

import asyncio

import pytest

from antragsplattform_mcp.tests.test_todo_card_parts import _FakeApi
from antragsplattform_mcp.tools import _common, events


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_event_get_reads_the_event_and_its_sales(fake_api: _FakeApi) -> None:
    """The Event carries the section "Verkauf" under `sales`."""
    result = asyncio.run(events.event_get("e1"))
    assert result == {"sales": {}}
    assert fake_api.calls == [("GET", "/events/e1", None), ("GET", "/events/e1/sales", None)]


def test_no_tool_links_or_calls_pretix_or_mollie() -> None:
    """No tool module names a route of the link, the refresh or the run."""
    from pathlib import Path

    tools = Path(events.__file__).parent
    text = "".join(p.read_text() for p in tools.glob("*.py"))
    for path in ("/pretix/", "/sales/refresh", "/sales-sync", "/admin/pretix", "/admin/mollie"):
        assert path not in text
