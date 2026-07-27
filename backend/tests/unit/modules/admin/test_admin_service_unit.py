"""Unit tests without a DB: ConfigService paths that run before any session access.

``create_global_flow_version`` validates the graph BEFORE it touches the DB. An invalid
flow ends as 422 (``ValidationProblem``), not as 500. The service never touches the
session, so these tests need no DB. The module also covers the date helpers.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.modules.admin.schemas import FlowVersionCreate
from app.modules.admin.service import ConfigService
from app.modules.admin.service.service_base import _iso, _parse_dt
from app.shared.config_schemas import FlowGraph
from app.shared.errors import ValidationProblem


def _svc() -> ConfigService:
    return ConfigService(None)  # type: ignore[arg-type]  — the session is unused before validation


def test_create_flow_version_no_initial_is_422_before_db() -> None:
    graph = FlowGraph.model_validate(
        {"states": [{"key": "draft", "label": {"de": "E"}, "isInitial": False}], "transitions": []}
    )
    with pytest.raises(ValidationProblem) as ei:
        asyncio.run(_svc().create_global_flow_version(FlowVersionCreate(graph=graph), "admin"))
    assert ei.value.status == 422
    assert ei.value.errors is not None
    assert ei.value.errors[0].field == "graph"


def test_create_flow_version_unreachable_state_is_422() -> None:
    graph = FlowGraph.model_validate(
        {
            "states": [
                {"key": "a", "label": {"de": "A"}, "isInitial": True},
                {"key": "b", "label": {"de": "B"}},
            ],
            "transitions": [],
        }
    )
    with pytest.raises(ValidationProblem):
        asyncio.run(_svc().create_global_flow_version(FlowVersionCreate(graph=graph), "admin"))


def test_create_flow_version_unknown_guard_operator_is_422() -> None:
    graph = FlowGraph.model_validate(
        {
            "states": [{"key": "a", "label": {"de": "A"}, "isInitial": True}],
            "transitions": [{"from": "a", "to": "a", "guard": {"bogusOp": True}}],
        }
    )
    with pytest.raises(ValidationProblem):
        asyncio.run(_svc().create_global_flow_version(FlowVersionCreate(graph=graph), "admin"))


def test_parse_dt_normalizes_to_aware_utc_and_none() -> None:
    assert _parse_dt(None) is None
    # A tz-aware input becomes aware UTC. The column is timestamptz since migration 0015.
    assert _parse_dt("2026-06-07T12:00:00+02:00") == datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    # The parser reads a naive input as UTC and returns an aware value.
    assert _parse_dt("2026-06-07T10:00:00") == datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    # _iso emits the UTC offset.
    assert _iso(_parse_dt("2026-06-07T10:00:00")) == "2026-06-07T10:00:00+00:00"


def test_parse_dt_invalid_raises_422() -> None:
    with pytest.raises(ValidationProblem) as ei:
        _parse_dt("not-a-date")
    assert ei.value.status == 422


def test_iso_helper() -> None:
    assert _iso(None) is None
    iso = _iso(datetime(2026, 1, 2, tzinfo=UTC))
    assert iso is not None and iso.startswith("2026-01-02T")
