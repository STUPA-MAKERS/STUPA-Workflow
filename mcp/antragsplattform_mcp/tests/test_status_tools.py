"""§F/administration/admin/003035: the status tools send the requests of the status routes."""

from __future__ import annotations

import asyncio

import pytest

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.tests.test_todo_card_parts import _FakeApi
from antragsplattform_mcp.tools import _common, admin


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_status_tools_read_and_replace_a_list(fake_api: _FakeApi) -> None:
    """An agent reads a list, reads it with the counts and replaces it with a replacement."""
    payload = S.StatusListSet(
        statuses=[
            S.StatusIn(key="open", name={"de": "Offen"}, phase="open", start=True),
            S.StatusIn(key="done", name={"de": "Fertig"}, phase="done", setsDate="deliveredOn"),
            S.StatusIn(key="gone", name={"de": "Weg"}, tone="muted", phase="void"),
        ],
        replacements={"cancelled": "gone"},
    )
    asyncio.run(admin.status_list("event"))
    asyncio.run(admin.admin_status_list("order"))
    asyncio.run(admin.admin_set_status_list("order", payload))
    assert fake_api.calls[:2] == [
        ("GET", "/statuses/event", None),
        ("GET", "/admin/statuses/order", None),
    ]
    method, path, body = fake_api.calls[2]
    assert (method, path) == ("PUT", "/admin/statuses/order")
    assert body["replacements"] == {"cancelled": "gone"}
    assert body["statuses"][0] == {
        "key": "open",
        "name": {"de": "Offen"},
        "tone": "neutral",
        "phase": "open",
        "start": True,
    }
    assert body["statuses"][1]["setsDate"] == "deliveredOn"
