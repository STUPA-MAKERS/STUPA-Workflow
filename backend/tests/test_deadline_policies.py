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


# --------------------------------------------------------------------------- #
# Flow-Enforcement: schedule_state_deadline + guard scanner
# --------------------------------------------------------------------------- #
from types import SimpleNamespace  # noqa: E402

from app.modules.flow.service import (  # noqa: E402
    FlowService,
    _guard_fires_on_deadline,
)
from tests.flow_fakes import fake_session, result  # noqa: E402


def test_guard_scanner_detects_deadline_passed_nested() -> None:
    assert _guard_fires_on_deadline({"deadlinePassed": True}) is True
    assert _guard_fires_on_deadline({"deadlinePassed": False}) is False
    assert _guard_fires_on_deadline({"and": [{"manual": True}, {"deadlinePassed": True}]}) is True
    assert _guard_fires_on_deadline({"or": [{"roleIs": "x"}, {"manual": True}]}) is False
    assert _guard_fires_on_deadline({"not": {"deadlinePassed": True}}) is True
    assert _guard_fires_on_deadline(None) is False


@pytest.mark.asyncio
async def test_schedule_state_deadline_creates_row_for_policy() -> None:
    flow_id, state_id, trans_id = uuid4(), uuid4(), uuid4()
    policy = _policy("relative_submitted", offset_days=10)
    policy.id = uuid4()
    transition = SimpleNamespace(id=trans_id, guard={"deadlinePassed": True})
    # execute-Queue: (1) get_by_key→policy, (2) outgoing transitions, (3) delete
    session = fake_session(result(policy), result(transition), result())
    app = SimpleNamespace(id=uuid4(), flow_version_id=flow_id, created_at=_NOW, updated_at=_NOW)
    state = SimpleNamespace(id=state_id, config={"deadlinePolicyKey": "k"})

    await FlowService(session).schedule_state_deadline(app, state)

    created = [o for o in session.added if getattr(o, "kind", None) == "flow_deadline"]
    assert len(created) == 1
    assert created[0].due_at == _NOW + timedelta(days=10)
    assert created[0].action_on_pass == {"transitionId": str(trans_id)}


@pytest.mark.asyncio
async def test_schedule_state_deadline_noop_without_policy_key() -> None:
    session = fake_session()
    app = SimpleNamespace(id=uuid4(), flow_version_id=uuid4(), created_at=_NOW, updated_at=_NOW)
    state = SimpleNamespace(id=uuid4(), config={})
    await FlowService(session).schedule_state_deadline(app, state)
    assert session.added == []
