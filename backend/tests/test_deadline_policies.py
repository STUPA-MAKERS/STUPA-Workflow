"""Deadline-Policy-Registry: reine ``resolve_due_at``-Logik + Router-Verdrahtung.

Die DB-Schicht (``DeadlinePolicyService``) wird per ``dependency_overrides`` durch
ein Fake ersetzt; Auth über ``get_current_principal``. ``resolve_due_at`` ist pur
und ohne DB getestet.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.deadlines.models import DeadlinePolicy
from app.modules.deadlines.router import get_service
from app.modules.deadlines.service import resolve_due_at

# --------------------------------------------------------------------------- #
# resolve_due_at (pur)
# --------------------------------------------------------------------------- #
_NOW = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)


def _policy(kind: str, **kw: object) -> DeadlinePolicy:
    return DeadlinePolicy(key="k", label={"de": "X"}, kind=kind, **kw)


def test_resolve_absolute_returns_fixed_date() -> None:
    p = _policy("absolute", absolute_at=_NOW)
    assert resolve_due_at(p, submitted_at=None) == _NOW


def test_resolve_relative_submitted_adds_offset() -> None:
    p = _policy("relative_submitted", offset_days=14)
    assert resolve_due_at(p, submitted_at=_NOW) == _NOW + timedelta(days=14)


def test_resolve_relative_changed_adds_offset() -> None:
    p = _policy("relative_changed", offset_days=7)
    assert resolve_due_at(p, changed_at=_NOW) == _NOW + timedelta(days=7)


def test_resolve_relative_without_reference_is_none() -> None:
    p = _policy("relative_submitted", offset_days=14)
    assert resolve_due_at(p, submitted_at=None) is None


# --------------------------------------------------------------------------- #
# Router-Verdrahtung
# --------------------------------------------------------------------------- #
class _FakeService:
    def __init__(self) -> None:
        self.created: dict | None = None

    async def list(self) -> list[DeadlinePolicy]:
        p = DeadlinePolicy(key="semester", label={"de": "Semester"}, kind="absolute", absolute_at=_NOW)
        p.id = uuid4()
        return [p]

    async def create(self, **kw):  # noqa: ANN003
        self.created = kw
        p = DeadlinePolicy(
            key=kw["key"], label=kw["label"], kind=kw["kind"],
            absolute_at=kw["absolute_at"], offset_days=kw["offset_days"],
        )
        p.id = uuid4()
        return p


@pytest.fixture
def fake_service() -> _FakeService:
    return _FakeService()


@pytest.fixture
def app(fake_service: _FakeService) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_service] = lambda: fake_service
    return application


@pytest.fixture
def app_client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as_admin(app: FastAPI) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions={"admin.config"}
    )


def test_list_requires_admin_config(app: FastAPI, app_client: TestClient) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="u", permissions=set()
    )
    assert app_client.get("/api/admin/deadline-policies").status_code == 403


def test_list_ok(app: FastAPI, app_client: TestClient) -> None:
    _as_admin(app)
    res = app_client.get("/api/admin/deadline-policies")
    assert res.status_code == 200
    assert res.json()[0]["key"] == "semester"


def test_create_relative_policy(
    app: FastAPI, app_client: TestClient, fake_service: _FakeService
) -> None:
    _as_admin(app)
    res = app_client.post(
        "/api/admin/deadline-policies",
        json={"key": "edit_window", "label": {"de": "Frist"}, "kind": "relative_changed", "offsetDays": 7},
    )
    assert res.status_code == 201
    assert res.json()["kind"] == "relative_changed"
    assert fake_service.created is not None and fake_service.created["offset_days"] == 7
