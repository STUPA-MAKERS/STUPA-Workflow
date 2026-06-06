"""Router-Tests Budget (T-17): Endpunkt-Verdrahtung ohne DB (Service-Fake).

Auth (Principal) und ``BudgetService`` werden per ``dependency_overrides`` ersetzt;
echte DB-Pfade liegen in der Integration. Deckt jede Route + den Service-Factory-Hook.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.budget.router import ServiceDep, get_budget_service
from app.modules.budget.schemas import (
    AssignOut,
    BudgetPotDetailOut,
    BudgetPotOut,
    BudgetStatsOut,
    PotUsageOut,
)
from app.modules.budget.service import BudgetService

_PID = uuid.uuid4()
_GID = uuid.uuid4()
_AID = uuid.uuid4()

_PERMS = ("budget.manage", "budget.view", "application.manage")


def _pot_out() -> BudgetPotOut:
    return BudgetPotOut(
        id=_PID, gremiumId=_GID, name="Topf", total=Decimal("100"),
        currency="EUR", period="2026", active=True, fields=[],
    )


def _usage() -> PotUsageOut:
    return PotUsageOut(
        budgetPotId=_PID, period="2026", total=Decimal("100"), currency="EUR",
        requested=Decimal("0"), reserved=Decimal("0"), approved=Decimal("0"),
        paid=Decimal("0"), committed=Decimal("0"), available=Decimal("100"),
    )


class _FakeStats:
    async def stats(self, **kwargs: object) -> BudgetStatsOut:
        self.kwargs = kwargs
        return BudgetStatsOut(pots=[_usage()], statusDistribution=[])


class _FakeService:
    def __init__(self) -> None:
        self.calls: dict[str, Any] = {}

    async def create_pot(self, payload: object) -> BudgetPotOut:
        self.calls["create"] = payload
        return _pot_out()

    async def list_pots(self, **kwargs: object) -> list[BudgetPotOut]:
        self.calls["list"] = kwargs
        return [_pot_out()]

    async def get_pot(self, pot_id: uuid.UUID) -> BudgetPotDetailOut:
        self.calls["get"] = pot_id
        return BudgetPotDetailOut(pot=_pot_out(), usage=_usage())

    async def update_pot(self, pot_id: uuid.UUID, payload: object) -> BudgetPotOut:
        self.calls["update"] = (pot_id, payload)
        return _pot_out()

    async def assign(self, application_id: uuid.UUID, payload: object, *, actor: str) -> AssignOut:
        self.calls["assign"] = {"app": application_id, "actor": actor}
        return AssignOut(
            applicationId=application_id, gremiumId=_GID, budgetPotId=_PID,
            stage="requested", amount=Decimal("50"), currency="EUR",
        )

    def stats_service(self) -> _FakeStats:
        return _FakeStats()


@pytest.fixture
def fake() -> _FakeService:
    return _FakeService()


@pytest.fixture
def client(fake: _FakeService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_budget_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions=set(_PERMS)
    )
    app.dependency_overrides[get_current_applicant] = lambda: None
    return TestClient(app)


def test_create_pot(client: TestClient, fake: _FakeService) -> None:
    resp = client.post(
        "/api/budget-pots",
        json={"gremiumId": str(_GID), "name": "Topf", "total": "100.00"},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Topf"
    assert "create" in fake.calls


def test_list_pots(client: TestClient, fake: _FakeService) -> None:
    resp = client.get("/api/budget-pots", params={"gremium": str(_GID), "active": "true"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert fake.calls["list"]["gremium_id"] == _GID


def test_get_pot(client: TestClient, fake: _FakeService) -> None:
    resp = client.get(f"/api/budget-pots/{_PID}")
    assert resp.status_code == 200
    assert resp.json()["pot"]["id"] == str(_PID)


def test_update_pot(client: TestClient, fake: _FakeService) -> None:
    resp = client.patch(f"/api/budget-pots/{_PID}", json={"name": "Neu"})
    assert resp.status_code == 200
    assert fake.calls["update"][0] == _PID


def test_assign(client: TestClient, fake: _FakeService) -> None:
    resp = client.post(
        f"/api/applications/{_AID}/assign", json={"budgetPotId": str(_PID)}
    )
    assert resp.status_code == 200
    assert resp.json()["stage"] == "requested"
    assert fake.calls["assign"]["actor"] == "admin"


def test_stats(client: TestClient) -> None:
    resp = client.get("/api/budget/stats", params={"pot": str(_PID), "period": "2026"})
    assert resp.status_code == 200
    assert len(resp.json()["pots"]) == 1


def test_forbidden_without_permission(fake: _FakeService) -> None:
    app = create_app()
    app.dependency_overrides[get_budget_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="x", permissions=set()
    )
    app.dependency_overrides[get_current_applicant] = lambda: None
    resp = TestClient(app).get("/api/budget-pots")
    assert resp.status_code == 403


def test_get_budget_service_factory() -> None:
    # Deckt die Service-Factory (sonst durch Override umgangen).
    svc = get_budget_service(session=object())  # type: ignore[arg-type]
    assert isinstance(svc, BudgetService)
    assert ServiceDep is not None
