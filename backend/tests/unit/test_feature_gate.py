"""Unit: the gate that closes the routes of a feature that is off.

§F/administration/admin/000757: each route of the feature answers 404
``feature_disabled``, also without a session and for a WebSocket.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import WebSocketException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.feature_routes import feature_gate
from app.main import create_app
from app.modules.auth.ws import WS_NOT_FOUND
from app.modules.site_config.features import FeatureDisabledError, FeatureSwitches


def _switches(monkeypatch: pytest.MonkeyPatch, **off: bool) -> list[object]:
    """Set the stored switches and return the list of the sessions that read them."""
    reads: list[object] = []

    async def read(session: object) -> FeatureSwitches:
        reads.append(session)
        return FeatureSwitches(**off)

    monkeypatch.setattr("app.modules.site_config.features.active_switches", read)
    return reads


def _connection(path: str, kind: str = "http") -> Any:
    return SimpleNamespace(scope={"type": kind, "route": SimpleNamespace(path=path)})


async def test_a_route_of_no_feature_costs_no_read(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _switches(monkeypatch, todos=False)
    await feature_gate(_connection("/api/applications"), object())  # type: ignore[arg-type]
    await feature_gate(SimpleNamespace(scope={"type": "http"}), object())  # type: ignore[arg-type]
    assert reads == []


async def test_a_route_of_a_feature_that_is_on_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _switches(monkeypatch, tickets=False)
    await feature_gate(_connection("/api/todos/boards"), object())  # type: ignore[arg-type]
    assert len(reads) == 1


async def test_a_route_of_a_feature_that_is_off_is_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _switches(monkeypatch, voting=False)
    with pytest.raises(FeatureDisabledError) as err:
        await feature_gate(
            _connection("/api/meetings/{meeting_id}/votes"),
            object(),  # type: ignore[arg-type]
        )
    assert "voting" in (err.value.detail or "")
    assert "meetings" not in (err.value.detail or "")


async def test_a_websocket_of_a_feature_that_is_off_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _switches(monkeypatch, todos=False)
    with pytest.raises(WebSocketException) as err:
        await feature_gate(
            _connection("/api/ws/todos", "websocket"),
            object(),  # type: ignore[arg-type]
        )
    assert err.value.code == WS_NOT_FOUND


def test_the_app_answers_feature_disabled_before_the_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _switches(monkeypatch, budget=False)
    with TestClient(create_app()) as client:
        budget = client.get("/api/budgets")
        invoices = client.post("/api/invoices/parse")
        other = client.get("/api/health")
    assert (budget.status_code, budget.json()["code"]) == (404, "feature_disabled")
    assert budget.headers["content-type"].startswith("application/problem+json")
    assert (invoices.status_code, invoices.json()["code"]) == (404, "feature_disabled")
    assert other.status_code == 200


def test_the_app_closes_a_websocket_of_a_feature_that_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _switches(monkeypatch, todos=False)
    with (
        TestClient(create_app()) as client,
        pytest.raises(WebSocketDisconnect) as err,
        client.websocket_connect("/api/ws/todos"),
    ):
        pass
    assert err.value.code == WS_NOT_FOUND
