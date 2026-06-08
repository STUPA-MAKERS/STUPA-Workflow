"""Router-Tests Budget-Baum (CR #76/#78): Endpunkt-Verdrahtung ohne DB (Service-Fake).

Auth (Principal) + ``BudgetTreeService`` per ``dependency_overrides``; echte DB-Pfade
liegen in der Integration. Deckt jede Route + den Service-Factory-Hook.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.budget.tree_router import ServiceDep, get_budget_tree_service
from app.modules.budget.tree_schemas import (
    AllocationOut,
    AssignBudgetOut,
    BudgetNodeOut,
    BudgetTreeNodeOut,
    FiscalYearOut,
)
from app.modules.budget.tree_service import BudgetTreeService

_BID = uuid.uuid4()
_GID = uuid.uuid4()
_FYID = uuid.uuid4()
_AID = uuid.uuid4()
_PERMS = ("budget.manage", "budget.view", "application.manage")


def _node_out() -> BudgetNodeOut:
    return BudgetNodeOut(
        id=_BID, parentId=None, gremiumId=_GID, key="VS",
        pathKey="VS", name="VS-Mittel", currency="EUR", active=True,
    )


class _FakeService:
    def __init__(self) -> None:
        self.calls: dict[str, Any] = {}

    async def get_tree(self, *, gremium_id: Any = None) -> list[BudgetTreeNodeOut]:
        self.calls["tree"] = gremium_id
        return [
            BudgetTreeNodeOut(
                id=_BID, parentId=None, gremiumId=_GID, key="VS", pathKey="VS",
                name="VS-Mittel", currency="EUR", active=True,
            )
        ]

    async def create_node(self, payload: object) -> BudgetNodeOut:
        self.calls["create"] = payload
        return _node_out()

    async def update_node(self, budget_id: uuid.UUID, payload: object) -> BudgetNodeOut:
        self.calls["update"] = budget_id
        return _node_out()

    async def delete_node(self, budget_id: uuid.UUID) -> None:
        self.calls["delete"] = budget_id

    async def list_fiscal_years(self, budget_id: uuid.UUID) -> list[FiscalYearOut]:
        self.calls["list_fy"] = budget_id
        return [_fy_out()]

    async def create_fiscal_year(self, budget_id: uuid.UUID, payload: object) -> FiscalYearOut:
        self.calls["create_fy"] = budget_id
        return _fy_out()

    async def update_fiscal_year(
        self, budget_id: uuid.UUID, fiscal_year_id: uuid.UUID, payload: object
    ) -> FiscalYearOut:
        self.calls["update_fy"] = (budget_id, fiscal_year_id)
        return _fy_out()

    async def set_allocation(
        self, budget_id: uuid.UUID, fiscal_year_id: uuid.UUID, payload: object
    ) -> AllocationOut:
        self.calls["alloc"] = (budget_id, fiscal_year_id)
        return AllocationOut(
            budgetId=budget_id, fiscalYearId=fiscal_year_id, allocated=Decimal("500")
        )

    async def assign_budget(self, application_id: uuid.UUID, payload: object) -> AssignBudgetOut:
        self.calls["assign"] = application_id
        return AssignBudgetOut(applicationId=application_id, budgetId=_BID, fiscalYearId=_FYID)

    async def move_fiscal_year(self, application_id: uuid.UUID, payload: object) -> AssignBudgetOut:
        self.calls["move"] = application_id
        return AssignBudgetOut(applicationId=application_id, budgetId=_BID, fiscalYearId=_FYID)


def _fy_out() -> FiscalYearOut:
    return FiscalYearOut(
        id=_FYID, budgetId=_BID, label="HHJ 2026",
        startDate=date(2026, 4, 1), endDate=date(2027, 3, 31), active=True,
    )


@pytest.fixture
def fake() -> _FakeService:
    return _FakeService()


@pytest.fixture
def client(fake: _FakeService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_budget_tree_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions=set(_PERMS)
    )
    app.dependency_overrides[get_current_applicant] = lambda: None
    return TestClient(app)


def test_list_tree(client: TestClient, fake: _FakeService) -> None:
    resp = client.get("/api/budgets", params={"gremium": str(_GID)})
    assert resp.status_code == 200
    assert resp.json()[0]["pathKey"] == "VS"
    assert fake.calls["tree"] == _GID


def test_create_node(client: TestClient, fake: _FakeService) -> None:
    resp = client.post(
        "/api/budgets", json={"key": "VS", "name": "VS-Mittel", "gremiumId": str(_GID)}
    )
    assert resp.status_code == 201
    assert resp.json()["pathKey"] == "VS"
    assert "create" in fake.calls


def test_update_node(client: TestClient, fake: _FakeService) -> None:
    resp = client.patch(f"/api/budgets/{_BID}", json={"name": "Neu"})
    assert resp.status_code == 200
    assert fake.calls["update"] == _BID


def test_delete_node(client: TestClient, fake: _FakeService) -> None:
    resp = client.delete(f"/api/budgets/{_BID}")
    assert resp.status_code == 204
    assert fake.calls["delete"] == _BID


def test_list_fiscal_years(client: TestClient, fake: _FakeService) -> None:
    resp = client.get(f"/api/budgets/{_BID}/fiscal-years")
    assert resp.status_code == 200
    assert resp.json()[0]["label"] == "HHJ 2026"


def test_create_fiscal_year(client: TestClient, fake: _FakeService) -> None:
    resp = client.post(
        f"/api/budgets/{_BID}/fiscal-years",
        json={"label": "HHJ 2026", "startDate": "2026-04-01", "endDate": "2027-03-31"},
    )
    assert resp.status_code == 201
    assert fake.calls["create_fy"] == _BID


def test_update_fiscal_year(client: TestClient, fake: _FakeService) -> None:
    resp = client.patch(
        f"/api/budgets/{_BID}/fiscal-years/{_FYID}", json={"label": "HHJ neu"}
    )
    assert resp.status_code == 200
    assert fake.calls["update_fy"] == (_BID, _FYID)


def test_set_allocation(client: TestClient, fake: _FakeService) -> None:
    resp = client.put(
        f"/api/budgets/{_BID}/allocations/{_FYID}", json={"allocated": "500.00"}
    )
    assert resp.status_code == 200
    assert resp.json()["allocated"] == "500"
    assert fake.calls["alloc"] == (_BID, _FYID)


def test_assign_budget(client: TestClient, fake: _FakeService) -> None:
    resp = client.post(f"/api/applications/{_AID}/assign-budget", json={"budgetId": str(_BID)})
    assert resp.status_code == 200
    assert resp.json()["fiscalYearId"] == str(_FYID)
    assert fake.calls["assign"] == _AID


def test_move_fiscal_year(client: TestClient, fake: _FakeService) -> None:
    resp = client.post(
        f"/api/applications/{_AID}/move-fiscal-year", json={"fiscalYearId": str(_FYID)}
    )
    assert resp.status_code == 200
    assert fake.calls["move"] == _AID


def test_forbidden_without_permission(fake: _FakeService) -> None:
    app = create_app()
    app.dependency_overrides[get_budget_tree_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="x", permissions=set())
    app.dependency_overrides[get_current_applicant] = lambda: None
    resp = TestClient(app).get("/api/budgets")
    assert resp.status_code == 403


def test_get_budget_tree_service_factory() -> None:
    svc = get_budget_tree_service(session=object())  # type: ignore[arg-type]
    assert isinstance(svc, BudgetTreeService)
    assert ServiceDep is not None
