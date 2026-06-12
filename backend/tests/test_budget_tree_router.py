"""Router-Tests Budget-Baum (CR #76/#78): Endpunkt-Verdrahtung ohne DB (Service-Fake).

Auth (Principal) + ``BudgetTreeService`` per ``dependency_overrides``; echte DB-Pfade
liegen in der Integration. Deckt jede Route + den Service-Factory-Hook.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date
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
    ExpenseOut,
    FiscalYearOut,
)
from app.modules.budget.tree_service import BudgetTreeService

_BID = uuid.uuid4()
_GID = uuid.uuid4()
_FYID = uuid.uuid4()
_AID = uuid.uuid4()
_EID = uuid.uuid4()
_PERMS = ("budget.structure", "budget.book", "budget.view", "application.manage")


def _expense_out() -> ExpenseOut:
    from datetime import datetime

    return ExpenseOut(
        id=_EID, budgetId=_BID, pathKey="VS", fiscalYearId=_FYID,
        amount=Decimal("42.00"), currency="EUR", description="Rechnung",
        actor="admin", createdAt=datetime(2026, 6, 9, tzinfo=UTC),
    )


def _node_out() -> BudgetNodeOut:
    return BudgetNodeOut(
        id=_BID, parentId=None, gremiumId=_GID, key="VS",
        pathKey="VS", name="VS-Mittel", currency="EUR", active=True,
    )


class _FakeAuditResult:
    def scalar_one_or_none(self) -> None:
        return None


class _FakeAuditSession:
    """Minimal-Session für den Audit-Hook in Export-Endpunkten (kein DB-Zugriff)."""

    def __init__(self) -> None:
        self.entries: list[Any] = []
        self.committed = False

    async def execute(self, _stmt: object) -> _FakeAuditResult:
        return _FakeAuditResult()

    def add(self, obj: object) -> None:
        self.entries.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True


class _FakeService:
    def __init__(self) -> None:
        self.calls: dict[str, Any] = {}
        self.session = _FakeAuditSession()

    async def get_tree(
        self, *, gremium_id: Any = None, visible_gremium_ids: Any = None
    ) -> list[BudgetTreeNodeOut]:
        self.calls["tree"] = gremium_id
        self.calls["scope"] = visible_gremium_ids
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

    async def create_expense(
        self, budget_id: uuid.UUID, payload: object, *, actor: str
    ) -> ExpenseOut:
        self.calls["create_expense"] = (budget_id, actor)
        return _expense_out()

    async def list_expenses(
        self, budget_id: uuid.UUID, fiscal_year_id: Any = None
    ) -> list[ExpenseOut]:
        self.calls["list_expenses"] = (budget_id, fiscal_year_id)
        return [_expense_out()]

    async def delete_expense(self, expense_id: uuid.UUID) -> None:
        self.calls["delete_expense"] = expense_id

    async def fiscal_year_label_map(self) -> dict[uuid.UUID, str]:
        self.calls["fy_labels"] = True
        return {_FYID: "2026"}


def _fy_out() -> FiscalYearOut:
    return FiscalYearOut(
        id=_FYID, budgetId=_BID, year=2026, display="2026",
        startDate=date(2026, 1, 1), endDate=date(2026, 12, 31), active=True,
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
    assert resp.json()[0]["year"] == 2026
    assert resp.json()[0]["display"] == "2026"


def test_create_fiscal_year(client: TestClient, fake: _FakeService) -> None:
    resp = client.post(
        f"/api/budgets/{_BID}/fiscal-years",
        json={"year": 2026},
    )
    assert resp.status_code == 201
    assert fake.calls["create_fy"] == _BID


def test_update_fiscal_year(client: TestClient, fake: _FakeService) -> None:
    resp = client.patch(
        f"/api/budgets/{_BID}/fiscal-years/{_FYID}", json={"active": False}
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


def test_create_expense(client: TestClient, fake: _FakeService) -> None:
    resp = client.post(
        f"/api/budgets/{_BID}/expenses",
        json={"amount": "42.00", "description": "Rechnung", "fiscalYearId": str(_FYID)},
    )
    assert resp.status_code == 201
    assert resp.json()["amount"] == "42.00"
    assert fake.calls["create_expense"] == (_BID, "admin")


def test_list_expenses(client: TestClient, fake: _FakeService) -> None:
    resp = client.get(f"/api/budgets/{_BID}/expenses", params={"fiscalYear": str(_FYID)})
    assert resp.status_code == 200
    assert resp.json()[0]["description"] == "Rechnung"
    assert fake.calls["list_expenses"] == (_BID, _FYID)


def test_delete_expense(client: TestClient, fake: _FakeService) -> None:
    resp = client.delete(f"/api/budget-expenses/{_EID}")
    assert resp.status_code == 204
    assert fake.calls["delete_expense"] == _EID


def test_create_expense_forbidden_for_viewer(fake: _FakeService) -> None:
    app = create_app()
    app.dependency_overrides[get_budget_tree_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="v", permissions={"budget.view"}
    )
    app.dependency_overrides[get_current_applicant] = lambda: None
    resp = TestClient(app).post(
        f"/api/budgets/{_BID}/expenses", json={"amount": "1.00", "description": "x"}
    )
    assert resp.status_code == 403


def test_tree_without_permission_is_gremium_scoped(
    fake: _FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#budget-scope: ohne budget.*-Permission liefert der Baum den Gremium-Scope
    (Mitglieds-Gremien als visible_gremium_ids); ohne Mitgliedschaften leer."""
    import app.modules.admin.gremium_roles as gr

    async def _members(session, sub, now=None):  # noqa: ANN001, ANN202
        return set()

    monkeypatch.setattr(gr, "gremium_member_ids", _members)
    app = create_app()
    app.dependency_overrides[get_budget_tree_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="x", permissions=set())
    app.dependency_overrides[get_current_applicant] = lambda: None
    resp = TestClient(app).get("/api/budgets")
    assert resp.status_code == 200
    assert fake.calls["scope"] == set()


def test_tree_full_view_is_unscoped(fake: _FakeService) -> None:
    app = create_app()
    app.dependency_overrides[get_budget_tree_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="x", permissions={"budget.view"}
    )
    app.dependency_overrides[get_current_applicant] = lambda: None
    resp = TestClient(app).get("/api/budgets")
    assert resp.status_code == 200
    assert fake.calls["scope"] is None


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_budget_export_requires_permission(fake: _FakeService) -> None:
    app = create_app()
    app.dependency_overrides[get_budget_tree_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="x", permissions={"budget.view"}
    )
    app.dependency_overrides[get_current_applicant] = lambda: None
    resp = TestClient(app).get("/api/budget/export.xlsx")
    assert resp.status_code == 403


def test_budget_export_xlsx(fake: _FakeService) -> None:
    app = create_app()
    app.dependency_overrides[get_budget_tree_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="fin", permissions={"budget.export"}
    )
    app.dependency_overrides[get_current_applicant] = lambda: None
    resp = TestClient(app).get("/api/budget/export.xlsx", params={"gremium": str(_GID)})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(_XLSX)
    assert "budget.xlsx" in resp.headers["content-disposition"]
    assert resp.content[:2] == b"PK"  # xlsx = zip container
    assert fake.calls["tree"] == _GID
    assert fake.calls["fy_labels"] is True
    # Export wird auditiert (#1): EXPORT-Eintrag + Commit in derselben Transaktion.
    (entry,) = fake.session.entries
    assert entry.action == "export"
    assert entry.actor == "fin"
    assert entry.target_id == "budget.xlsx"
    assert fake.session.committed is True


def test_get_budget_tree_service_factory() -> None:
    svc = get_budget_tree_service(session=object())  # type: ignore[arg-type]
    assert isinstance(svc, BudgetTreeService)
    assert ServiceDep is not None
