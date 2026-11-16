"""Tests for the agenda read tool and for the transport errors of the API client.

`get_agenda` reads `GET /meetings/{id}/agenda`. A request without an answer must reach
the agent as an `ApiError` with a message, never as an exception with an empty text,
and a failed write must tell the agent to read before it repeats the call.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from antragsplattform_mcp import client as client_mod
from antragsplattform_mcp.client import ApiClient, ApiError
from antragsplattform_mcp.config import Config
from antragsplattform_mcp.tools import _common, meetings


class _FakeApi:
    """Record each GET and answer with one agenda item."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get(self, path: str, **kw: Any) -> list[dict[str, Any]]:
        self.calls.append(("GET", path))
        return [{"id": "i1", "title": "TOP 1", "position": 0}]


def test_get_agenda_reads_the_agenda_route(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    items = asyncio.run(meetings.get_agenda("m1"))
    assert fake.calls == [("GET", "/meetings/m1/agenda")]
    assert items == [{"id": "i1", "title": "TOP 1", "position": 0}]


class _PostApi:
    """Record each POST and answer with an empty agenda."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def post(self, path: str, **kw: Any) -> list[dict[str, Any]]:
        self.calls.append((path, kw.get("json")))
        return []


def test_add_agenda_item_sends_the_description(monkeypatch: pytest.MonkeyPatch) -> None:
    """§000861: a free-text item takes a description."""
    fake = _PostApi()
    monkeypatch.setattr(_common, "_client", fake)
    asyncio.run(meetings.add_agenda_item("m1", title="Bericht", description="Info"))
    asyncio.run(meetings.add_agenda_item("m1", title="Kurz"))
    assert fake.calls == [
        ("/meetings/m1/agenda", {"title": "Bericht", "description": "Info"}),
        ("/meetings/m1/agenda", {"title": "Kurz"}),
    ]


def _client(handler: Any, monkeypatch: pytest.MonkeyPatch) -> ApiClient:
    monkeypatch.setattr(
        client_mod.auth, "ensure_access_token", lambda *_a, **_k: "token"
    )
    api = ApiClient(Config(base_url="https://example.test", scope="read"))
    api._client = httpx.AsyncClient(
        base_url="https://example.test/api", transport=httpx.MockTransport(handler)
    )
    return api


def test_timeout_without_text_gets_a_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    api = _client(handler, monkeypatch)
    with pytest.raises(ApiError) as exc:
        asyncio.run(api.post("/meetings/m1/agenda", json={"title": "x"}))
    text = str(exc.value)
    assert exc.value.status == 0
    assert "ReadTimeout" in text
    assert "POST /meetings/m1/agenda" in text
    assert "before you repeat" in text


def test_failed_read_has_no_write_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    api = _client(handler, monkeypatch)
    with pytest.raises(ApiError) as exc:
        asyncio.run(api.get("/meetings/m1/agenda"))
    text = str(exc.value)
    assert "ConnectError: connection refused" in text
    assert "repeat" not in text


def test_http_error_keeps_status_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "meeting_closed"})

    api = _client(handler, monkeypatch)
    with pytest.raises(ApiError) as exc:
        asyncio.run(api.post("/meetings/m1/agenda", json={"title": "x"}))
    assert str(exc.value) == "409: meeting_closed"


def test_add_agenda_item_sends_the_plan_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """§F/finance/budget/000838: a waiting plan goes on the agenda by its version."""
    fake = _PostApi()
    monkeypatch.setattr(_common, "_client", fake)
    asyncio.run(meetings.add_agenda_item("m1", plan_version_id="pv1"))
    assert fake.calls == [("/meetings/m1/agenda", {"planVersionId": "pv1"})]
