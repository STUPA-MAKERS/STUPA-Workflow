"""Zusatz-Coverage Budget-Baum (#76/#78): Router-Endpunkte, Schema-Validatoren und
ZUGFeRD-Import-Hilfsfunktionen, die die bestehenden Suiten nicht berühren.

Reine Unit-Tests ohne DB/MinIO/Netz: der Router läuft mit einem vollständigen
Service-Fake (``dependency_overrides``); ``invoice_import`` wird größtenteils direkt
über seine reinen Funktionen + ``SimpleNamespace``-Stubs angesteuert (kein PDF nötig
außer für ``_extract_cii_xml``-Grenzfälle, dort echte ``pypdf``-PDFs).
"""

from __future__ import annotations

import io
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.budget import invoice_import as imp
from app.modules.budget.invoice_import import (
    NotZugferdError,
    UnsupportedInvoiceCurrencyError,
    _amount,
    _cii_date,
    _cii_decimal,
    _extract_cii_xml,
    _find_text,
    _map,
    _parse_cii_header,
    _require_sane_gross,
    _sane_amount,
    parse_zugferd_pdf,
)
from app.modules.budget.tree_router import (
    ServiceDep,
    _find_subtree,
    get_budget_tree_service,
)
from app.modules.budget.tree_schemas import (
    AccountOut,
    AllocationOut,
    AssignBudgetOut,
    BudgetApplicationOut,
    BudgetNodeOut,
    BudgetTreeNodeOut,
    ExpenseCreate,
    ExpenseOut,
    ExpenseUpdate,
    FiscalYearOut,
    InvoiceFileResult,
    InvoiceOut,
    InvoiceParseResult,
    InvoiceUpdate,
    TransferCreate,
    TransferOut,
)
from app.modules.budget.tree_service import BudgetTreeService
from app.settings import load_settings

# --------------------------------------------------------------------- ids
_BID = uuid.uuid4()
_GID = uuid.uuid4()
_FYID = uuid.uuid4()
_AID = uuid.uuid4()
_EID = uuid.uuid4()
_IID = uuid.uuid4()
_FROM = uuid.uuid4()
_TO = uuid.uuid4()
_ALL_PERMS = (
    "budget.structure",
    "budget.book",
    "budget.view",
    "budget.export",
    "account.manage",
    "application.manage",
)


# --------------------------------------------------------- DTO factories
def _expense_out() -> ExpenseOut:
    return ExpenseOut(
        id=_EID,
        budgetId=_BID,
        pathKey="VS",
        fiscalYearId=_FYID,
        amount=Decimal("42.00"),
        currency="EUR",
        description="Rechnung",
        actor="admin",
        createdAt=datetime(2026, 6, 9, tzinfo=UTC),
    )


def _invoice_out() -> InvoiceOut:
    return InvoiceOut(
        id=_IID,
        number="R-2026-1",
        grossAmount=Decimal("119.00"),
        currency="EUR",
        status="open",
        createdAt=datetime(2026, 6, 9, tzinfo=UTC),
    )


def _node_out() -> BudgetNodeOut:
    return BudgetNodeOut(
        id=_BID,
        parentId=None,
        gremiumId=_GID,
        key="VS",
        pathKey="VS",
        name="VS-Mittel",
        currency="EUR",
        active=True,
    )


def _fy_out() -> FiscalYearOut:
    return FiscalYearOut(
        id=_FYID,
        budgetId=_BID,
        year=2026,
        display="2026",
        startDate=date(2026, 1, 1),
        endDate=date(2026, 12, 31),
        active=True,
    )


def _tree_node() -> BudgetTreeNodeOut:
    return BudgetTreeNodeOut(
        id=_BID,
        parentId=None,
        gremiumId=_GID,
        key="VS",
        pathKey="VS",
        name="VS-Mittel",
        currency="EUR",
        active=True,
    )


# --------------------------------------------------------- audit fake session
class _FakeAuditResult:
    def scalar_one_or_none(self) -> None:
        return None


class _FakeAuditSession:
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


# --------------------------------------------------------- full service fake
class _FakeService:
    """Vollständiger Service-Fake — deckt jede vom Router gerufene Methode ab."""

    def __init__(self) -> None:
        self.calls: dict[str, Any] = {}
        self.session = _FakeAuditSession()
        self.can_view = True

    # ----- tree / nodes
    async def get_tree(
        self, *, gremium_id: Any = None, visible_gremium_ids: Any = None
    ) -> list[BudgetTreeNodeOut]:
        self.calls["tree"] = gremium_id
        self.calls["scope"] = visible_gremium_ids
        return [_tree_node()]

    async def can_view_node(self, budget_id: uuid.UUID, member: set[uuid.UUID]) -> bool:
        self.calls["can_view"] = (budget_id, member)
        return self.can_view

    async def create_node(self, payload: Any) -> BudgetNodeOut:
        self.calls["create_node"] = payload
        return _node_out()

    async def update_node(self, budget_id: uuid.UUID, payload: Any) -> BudgetNodeOut:
        self.calls["update_node"] = budget_id
        return _node_out()

    async def delete_node(self, budget_id: uuid.UUID) -> None:
        self.calls["delete_node"] = budget_id

    async def create_expense(
        self, budget_id: uuid.UUID, payload: Any, *, actor: str
    ) -> ExpenseOut:
        self.calls["create_expense"] = (budget_id, actor)
        return _expense_out()

    async def delete_expense(self, expense_id: uuid.UUID) -> None:
        self.calls["delete_expense"] = expense_id

    async def create_fiscal_year(self, budget_id: uuid.UUID, payload: Any) -> FiscalYearOut:
        self.calls["create_fy"] = budget_id
        return _fy_out()

    async def update_fiscal_year(
        self, budget_id: uuid.UUID, fiscal_year_id: uuid.UUID, payload: Any
    ) -> FiscalYearOut:
        self.calls["update_fy"] = (budget_id, fiscal_year_id)
        return _fy_out()

    async def set_allocation(
        self, budget_id: uuid.UUID, fiscal_year_id: uuid.UUID, payload: Any
    ) -> AllocationOut:
        self.calls["alloc"] = (budget_id, fiscal_year_id)
        return AllocationOut(
            budgetId=budget_id, fiscalYearId=fiscal_year_id, allocated=Decimal("500")
        )

    async def assign_budget(self, application_id: uuid.UUID, payload: Any) -> AssignBudgetOut:
        self.calls["assign"] = application_id
        return AssignBudgetOut(applicationId=application_id, budgetId=_BID, fiscalYearId=_FYID)

    async def move_fiscal_year(
        self, application_id: uuid.UUID, payload: Any
    ) -> AssignBudgetOut:
        self.calls["move"] = application_id
        return AssignBudgetOut(applicationId=application_id, budgetId=_BID, fiscalYearId=_FYID)

    async def list_account_options(self) -> list[Any]:
        from app.modules.budget.tree_schemas import AccountOption

        self.calls["list_account_options"] = True
        return [AccountOption(id=uuid.uuid4(), name="Hauptkonto")]

    async def list_invoices_paged(self, **kwargs: Any) -> Any:
        from app.shared.paging import Page

        self.calls["list_invoices_paged"] = kwargs
        return Page(items=[_invoice_out()], total=1, limit=kwargs.get("limit", 50), offset=0)

    async def create_invoice(self, payload: Any, *, actor: str) -> InvoiceOut:
        self.calls["create_invoice"] = (payload, actor)
        return _invoice_out()

    async def fiscal_year_label_map(self) -> dict[uuid.UUID, str]:
        return {_FYID: "2026"}

    # ----- applications scoped to node
    async def list_applications(
        self, budget_id: uuid.UUID, fiscal_year_id: Any
    ) -> list[BudgetApplicationOut]:
        self.calls["list_applications"] = (budget_id, fiscal_year_id)
        return [
            BudgetApplicationOut(
                applicationId=_AID,
                createdAt=datetime(2026, 6, 9, tzinfo=UTC),
            )
        ]

    async def list_expenses(
        self, budget_id: uuid.UUID, fiscal_year_id: Any = None
    ) -> list[ExpenseOut]:
        self.calls["list_expenses"] = (budget_id, fiscal_year_id)
        return [_expense_out()]

    async def list_fiscal_years(self, budget_id: uuid.UUID) -> list[Any]:
        self.calls["list_fy"] = budget_id
        return []

    # ----- expenses
    async def book_expense(self, payload: Any, *, actor: str) -> ExpenseOut:
        self.calls["book_expense"] = (payload, actor)
        return _expense_out()

    async def update_expense(self, expense_id: uuid.UUID, payload: Any) -> ExpenseOut:
        self.calls["update_expense"] = (expense_id, payload)
        return _expense_out()

    async def list_expenses_paged(self, **kwargs: Any) -> Any:
        from app.shared.paging import Page

        self.calls["list_expenses_paged"] = kwargs
        return Page(items=[_expense_out()], total=1, limit=kwargs.get("limit", 50), offset=0)

    # ----- transfers
    async def create_transfer(self, payload: Any, *, actor: str) -> TransferOut:
        self.calls["create_transfer"] = (payload, actor)
        return TransferOut(
            transferId=uuid.uuid4(), expenseId=uuid.uuid4(), incomeId=uuid.uuid4()
        )

    # ----- invoices
    async def get_invoice(self, invoice_id: uuid.UUID) -> InvoiceOut:
        self.calls["get_invoice"] = invoice_id
        return _invoice_out()

    async def update_invoice(self, invoice_id: uuid.UUID, payload: Any) -> InvoiceOut:
        self.calls["update_invoice"] = (invoice_id, payload)
        return _invoice_out()

    async def delete_invoice(self, invoice_id: uuid.UUID) -> None:
        self.calls["delete_invoice"] = invoice_id

    async def store_invoice_file(self, data: bytes, *, filename: str | None) -> InvoiceFileResult:
        self.calls["store_invoice_file"] = (len(data), filename)
        return InvoiceFileResult(
            fileToken="invoices/abc.pdf", fileName="abc.pdf", fileMime="application/pdf"
        )

    async def parse_invoice_file(
        self, data: bytes, *, filename: str | None
    ) -> InvoiceParseResult:
        self.calls["parse_invoice_file"] = (len(data), filename)
        return InvoiceParseResult(
            grossAmount=Decimal("119.00"),
            fileToken="invoices/abc.pdf",
            fileName="abc.pdf",
            fileMime="application/pdf",
        )

    async def invoice_file_bytes(self, invoice_id: uuid.UUID) -> tuple[bytes, str, str]:
        self.calls["invoice_file_bytes"] = invoice_id
        # Bewusst ein vom Client untergeschobener HTML-Mime: der Router darf ihm NICHT
        # vertrauen, sondern liefert hart als application/pdf-Attachment aus (#sec-audit).
        return (b"<html>polyglot</html>", "text/html", 'we"ird\r\nname.pdf')

    # ----- accounts
    async def list_accounts(self) -> list[AccountOut]:
        self.calls["list_accounts"] = True
        return [AccountOut(id=uuid.uuid4(), name="Hauptkonto", iban="DE00", active=True)]

    async def create_account(self, payload: Any) -> AccountOut:
        self.calls["create_account"] = payload
        return AccountOut(id=uuid.uuid4(), name="Neu", iban="", active=True)

    async def update_account(self, account_id: uuid.UUID, payload: Any) -> AccountOut:
        self.calls["update_account"] = (account_id, payload)
        return AccountOut(id=account_id, name="Geaendert", iban="DE11", active=False)

    async def delete_account(self, account_id: uuid.UUID) -> None:
        self.calls["delete_account"] = account_id


# --------------------------------------------------------- client helpers
@pytest.fixture
def fake() -> _FakeService:
    return _FakeService()


def _client(fake: _FakeService, perms: tuple[str, ...] = _ALL_PERMS) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_budget_tree_service] = lambda: fake
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions=set(perms)
    )
    app.dependency_overrides[get_current_applicant] = lambda: None
    return TestClient(app)


# =====================================================================
# ROUTER: service factory + tree full-view
# =====================================================================
def test_get_budget_tree_service_factory_with_storage() -> None:
    """Factory liest ``object_storage`` aus dem App-State und reicht ``sub`` als actor."""
    sentinel = object()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(object_storage=sentinel))
    )
    svc = get_budget_tree_service(
        session=object(),  # type: ignore[arg-type]
        request=request,  # type: ignore[arg-type]
        settings=load_settings(),
        principal=SimpleNamespace(sub="tester"),  # type: ignore[arg-type]
    )
    assert isinstance(svc, BudgetTreeService)
    assert svc.storage is sentinel
    assert svc.actor == "tester"
    assert ServiceDep is not None


def test_list_tree_full_view(fake: _FakeService) -> None:
    """Voll-Sicht ⇒ get_tree ohne visible_gremium_ids (Scope None)."""
    resp = _client(fake, ("budget.view",)).get("/api/budgets", params={"gremium": str(_GID)})
    assert resp.status_code == 200
    assert resp.json()[0]["pathKey"] == "VS"
    assert fake.calls["tree"] == _GID
    assert fake.calls["scope"] is None


def test_list_tree_gremium_scoped(
    fake: _FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ohne Voll-Sicht ⇒ Mitglieds-Gremien werden als visible_gremium_ids gereicht."""
    import app.modules.admin.gremium_roles as gr

    async def _members(session: Any, sub: Any, now: Any = None) -> set[uuid.UUID]:
        return {_GID}

    monkeypatch.setattr(gr, "gremium_member_ids", _members)
    resp = _client(fake, ()).get("/api/budgets")
    assert resp.status_code == 200
    assert fake.calls["scope"] == {_GID}


# =====================================================================
# ROUTER: basic node / fiscal-year / allocation / assign CRUD
# =====================================================================
def test_create_node(fake: _FakeService) -> None:
    resp = _client(fake).post(
        "/api/budgets", json={"key": "VS", "name": "VS-Mittel", "gremiumId": str(_GID)}
    )
    assert resp.status_code == 201
    assert "create_node" in fake.calls


def test_update_node(fake: _FakeService) -> None:
    resp = _client(fake).patch(f"/api/budgets/{_BID}", json={"name": "Neu"})
    assert resp.status_code == 200
    assert fake.calls["update_node"] == _BID


def test_delete_node(fake: _FakeService) -> None:
    resp = _client(fake).delete(f"/api/budgets/{_BID}")
    assert resp.status_code == 204
    assert fake.calls["delete_node"] == _BID


def test_create_expense_via_budget_path(fake: _FakeService) -> None:
    resp = _client(fake).post(
        f"/api/budgets/{_BID}/expenses",
        json={"amount": "42.00", "description": "Rechnung", "fiscalYearId": str(_FYID)},
    )
    assert resp.status_code == 201
    assert fake.calls["create_expense"] == (_BID, "admin")


def test_delete_budget_expense(fake: _FakeService) -> None:
    resp = _client(fake).delete(f"/api/budget-expenses/{_EID}")
    assert resp.status_code == 204
    assert fake.calls["delete_expense"] == _EID


def test_create_fiscal_year(fake: _FakeService) -> None:
    resp = _client(fake).post(f"/api/budgets/{_BID}/fiscal-years", json={"year": 2026})
    assert resp.status_code == 201
    assert fake.calls["create_fy"] == _BID


def test_update_fiscal_year(fake: _FakeService) -> None:
    resp = _client(fake).patch(
        f"/api/budgets/{_BID}/fiscal-years/{_FYID}", json={"active": False}
    )
    assert resp.status_code == 200
    assert fake.calls["update_fy"] == (_BID, _FYID)


def test_set_allocation(fake: _FakeService) -> None:
    resp = _client(fake).put(
        f"/api/budgets/{_BID}/allocations/{_FYID}", json={"allocated": "500.00"}
    )
    assert resp.status_code == 200
    assert fake.calls["alloc"] == (_BID, _FYID)


def test_assign_budget(fake: _FakeService) -> None:
    resp = _client(fake).post(
        f"/api/applications/{_AID}/assign-budget", json={"budgetId": str(_BID)}
    )
    assert resp.status_code == 200
    assert fake.calls["assign"] == _AID


def test_move_fiscal_year(fake: _FakeService) -> None:
    resp = _client(fake).post(
        f"/api/applications/{_AID}/move-fiscal-year", json={"fiscalYearId": str(_FYID)}
    )
    assert resp.status_code == 200
    assert fake.calls["move"] == _AID


def test_list_account_options(fake: _FakeService) -> None:
    resp = _client(fake, ("budget.book",)).get("/api/accounts/options")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "Hauptkonto"
    assert fake.calls["list_account_options"] is True


def test_list_invoices_paged(fake: _FakeService) -> None:
    resp = _client(fake, ("budget.view",)).get("/api/invoices?q=Acme&status=open")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["number"] == "R-2026-1"
    assert fake.calls["list_invoices_paged"]["q"] == "Acme"


def test_create_invoice(fake: _FakeService) -> None:
    resp = _client(fake).post("/api/invoices", json={"grossAmount": "119.00", "number": "R-1"})
    assert resp.status_code == 201
    assert fake.calls["create_invoice"][1] == "admin"


# =====================================================================
# ROUTER: node-scoped read (`_require_node_view`) — full-view + scope branches
# =====================================================================
def test_list_applications_full_view(fake: _FakeService) -> None:
    """Voll-Sicht (budget.view) ⇒ ``_require_node_view`` kehrt sofort zurück."""
    resp = _client(fake, ("budget.view",)).get(
        f"/api/budgets/{_BID}/applications", params={"fiscalYear": str(_FYID)}
    )
    assert resp.status_code == 200
    assert resp.json()[0]["applicationId"] == str(_AID)
    assert fake.calls["list_applications"] == (_BID, _FYID)
    # Voll-Sicht überspringt den Gremium-Scope-Check.
    assert "can_view" not in fake.calls


def test_list_applications_scoped_allowed(
    fake: _FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ohne Voll-Sicht: Mitglieds-Gremien werden geladen + ``can_view_node`` erlaubt."""
    import app.modules.admin.gremium_roles as gr

    async def _members(session: Any, sub: Any, now: Any = None) -> set[uuid.UUID]:
        return {_GID}

    monkeypatch.setattr(gr, "gremium_member_ids", _members)
    fake.can_view = True
    resp = _client(fake, ()).get(f"/api/budgets/{_BID}/applications")
    assert resp.status_code == 200
    assert fake.calls["can_view"] == (_BID, {_GID})


def test_list_expenses_scoped_denied(
    fake: _FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ohne Voll-Sicht + ``can_view_node`` False ⇒ 403 (ForbiddenError)."""
    import app.modules.admin.gremium_roles as gr

    async def _members(session: Any, sub: Any, now: Any = None) -> set[uuid.UUID]:
        return set()

    monkeypatch.setattr(gr, "gremium_member_ids", _members)
    fake.can_view = False
    resp = _client(fake, ()).get(f"/api/budgets/{_BID}/expenses")
    assert resp.status_code == 403
    assert "list_expenses" not in fake.calls


def test_list_expenses_scoped_allowed(
    fake: _FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.modules.admin.gremium_roles as gr

    async def _members(session: Any, sub: Any, now: Any = None) -> set[uuid.UUID]:
        return {_GID}

    monkeypatch.setattr(gr, "gremium_member_ids", _members)
    fake.can_view = True
    resp = _client(fake, ()).get(f"/api/budgets/{_BID}/expenses")
    assert resp.status_code == 200
    assert fake.calls["list_expenses"] == (_BID, None)


def test_list_fiscal_years_scoped_allowed(
    fake: _FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.modules.admin.gremium_roles as gr

    async def _members(session: Any, sub: Any, now: Any = None) -> set[uuid.UUID]:
        return {_GID}

    monkeypatch.setattr(gr, "gremium_member_ids", _members)
    fake.can_view = True
    resp = _client(fake, ()).get(f"/api/budgets/{_BID}/fiscal-years")
    assert resp.status_code == 200
    assert fake.calls["list_fy"] == _BID


# =====================================================================
# ROUTER: _find_subtree (recursion) via export with `node` filter
# =====================================================================
def test_find_subtree_direct() -> None:
    leaf = _tree_node()
    other = BudgetTreeNodeOut(
        id=uuid.uuid4(),
        parentId=None,
        gremiumId=_GID,
        key="X",
        pathKey="X",
        name="X",
        currency="EUR",
        active=True,
        children=[leaf],
    )
    # Treffer in der Wurzel.
    assert _find_subtree([other], other.id) is other
    # Treffer in einem Kind (Rekursion).
    assert _find_subtree([other], leaf.id) is leaf
    # Kein Treffer ⇒ None.
    assert _find_subtree([other], uuid.uuid4()) is None


def test_export_without_node_filter(fake: _FakeService) -> None:
    """Kein ``node`` ⇒ ``node_id is None``: Export des vollen (gefilterten) Baums."""
    resp = _client(fake, ("budget.export",)).get(
        "/api/budget/export.xlsx", params={"gremium": str(_GID)}
    )
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"
    assert fake.calls["tree"] == _GID
    (entry,) = fake.session.entries
    assert entry.data["node_id"] is None


def test_export_with_node_filter_found(fake: _FakeService) -> None:
    resp = _client(fake, ("budget.export",)).get(
        "/api/budget/export.xlsx", params={"node": str(_BID), "fiscalYear": str(_FYID)}
    )
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"
    (entry,) = fake.session.entries
    assert entry.action == "export"
    assert entry.target_id == "budget.xlsx"
    assert fake.session.committed is True


def test_export_with_node_filter_missing(fake: _FakeService) -> None:
    """``node`` ohne Treffer ⇒ leerer Export (kein 500)."""
    other_node = uuid.uuid4()
    resp = _client(fake, ("budget.export",)).get(
        "/api/budget/export.xlsx", params={"node": str(other_node)}
    )
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"


# =====================================================================
# ROUTER: expenses (flat book / update) + transfers
# =====================================================================
def test_book_expense_flat(fake: _FakeService) -> None:
    resp = _client(fake).post(
        "/api/expenses",
        json={"amount": "42.00", "description": "Rechnung", "budgetId": str(_BID)},
    )
    assert resp.status_code == 201
    assert resp.json()["amount"] == "42.00"
    assert fake.calls["book_expense"][1] == "admin"


def test_update_budget_expense(fake: _FakeService) -> None:
    resp = _client(fake).patch(
        f"/api/budget-expenses/{_EID}", json={"description": "Neu"}
    )
    assert resp.status_code == 200
    assert fake.calls["update_expense"][0] == _EID


def test_create_transfer(fake: _FakeService) -> None:
    resp = _client(fake).post(
        "/api/budget-transfers",
        json={
            "fromBudgetId": str(_FROM),
            "toBudgetId": str(_TO),
            "fiscalYearId": str(_FYID),
            "amount": "10.00",
            "description": "Umbuchung",
        },
    )
    assert resp.status_code == 201
    assert "transferId" in resp.json()
    assert fake.calls["create_transfer"][1] == "admin"


def test_export_expenses_xlsx(fake: _FakeService) -> None:
    resp = _client(fake, ("budget.export",)).get(
        "/api/expenses/export.xlsx",
        params={
            "budget": str(_BID),
            "fiscalYear": str(_FYID),
            "kind": "expense",
            "q": "Rechnung",
            "amountMin": "1",
            "amountMax": "100",
            "createdFrom": "2026-01-01",
            "createdTo": "2026-12-31",
        },
    )
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"
    assert "buchungen.xlsx" in resp.headers["content-disposition"]
    (entry,) = fake.session.entries
    assert entry.target_id == "buchungen.xlsx"
    assert entry.data["rows"] == 1
    assert fake.session.committed is True
    # list_expenses_paged wird mit limit=10_000 aufgerufen.
    assert fake.calls["list_expenses_paged"]["limit"] == 10_000


def test_export_expenses_requires_permission(fake: _FakeService) -> None:
    resp = _client(fake, ("budget.view",)).get("/api/expenses/export.xlsx")
    assert resp.status_code == 403


def test_list_expenses_paged_sort_passthrough(fake: _FakeService) -> None:
    """``sort`` wird unverändert an den Service durchgereicht — inkl. Datums-Spalten.

    Früher kollabierte der Router invoiceDate/paymentDate fälschlich auf createdAt → die
    Datums-Sortierung im Buchungen-Tab war wirkungslos (Regressionstest)."""
    _client(fake).get("/api/expenses?sort=amount&order=desc")
    assert fake.calls["list_expenses_paged"]["sort"] == "amount"
    _client(fake).get("/api/expenses?sort=invoiceDate")
    assert fake.calls["list_expenses_paged"]["sort"] == "invoiceDate"
    _client(fake).get("/api/expenses?sort=paymentDate&order=asc")
    assert fake.calls["list_expenses_paged"]["sort"] == "paymentDate"


# =====================================================================
# ROUTER: invoices CRUD + file endpoints
# =====================================================================
def test_get_invoice(fake: _FakeService) -> None:
    resp = _client(fake, ("budget.view",)).get(f"/api/invoices/{_IID}")
    assert resp.status_code == 200
    assert resp.json()["number"] == "R-2026-1"
    assert fake.calls["get_invoice"] == _IID


def test_update_invoice(fake: _FakeService) -> None:
    resp = _client(fake).patch(f"/api/invoices/{_IID}", json={"status": "paid"})
    assert resp.status_code == 200
    assert fake.calls["update_invoice"][0] == _IID


def test_update_invoice_requires_book(fake: _FakeService) -> None:
    resp = _client(fake, ("budget.view",)).patch(
        f"/api/invoices/{_IID}", json={"status": "paid"}
    )
    assert resp.status_code == 403


def test_delete_invoice(fake: _FakeService) -> None:
    resp = _client(fake).delete(f"/api/invoices/{_IID}")
    assert resp.status_code == 204
    assert fake.calls["delete_invoice"] == _IID


def test_upload_invoice_file(fake: _FakeService) -> None:
    resp = _client(fake).post(
        "/api/invoices/file",
        files={"file": ("beleg.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["fileToken"] == "invoices/abc.pdf"
    assert fake.calls["store_invoice_file"][1] == "beleg.pdf"


def test_parse_invoice_file_ok(fake: _FakeService) -> None:
    resp = _client(fake).post(
        "/api/invoices/parse",
        files={"file": ("r.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["grossAmount"] == "119.00"


def test_parse_invoice_currency_unsupported(fake: _FakeService) -> None:
    async def _raise(data: bytes, *, filename: str | None) -> InvoiceParseResult:
        raise UnsupportedInvoiceCurrencyError("USD")

    fake.parse_invoice_file = _raise  # type: ignore[assignment]
    resp = _client(fake).post(
        "/api/invoices/parse",
        files={"file": ("r.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "invoice_currency_unsupported"
    assert "USD" in resp.json()["detail"]


def test_parse_invoice_not_zugferd(fake: _FakeService) -> None:
    async def _raise(data: bytes, *, filename: str | None) -> InvoiceParseResult:
        raise NotZugferdError("no xml")

    fake.parse_invoice_file = _raise  # type: ignore[assignment]
    resp = _client(fake).post(
        "/api/invoices/parse",
        files={"file": ("r.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "invoice_not_zugferd"


def test_get_invoice_file_sanitises_filename(fake: _FakeService) -> None:
    resp = _client(fake, ("budget.view",)).get(f"/api/invoices/{_IID}/file")
    assert resp.status_code == 200
    cd = resp.headers["content-disposition"]
    # Sicherheits-Härtung (#sec-audit): Client-Mime ignoriert → hart application/pdf,
    # und Content-Disposition: attachment (kein Inline-Render des HTML-Polyglots).
    assert resp.headers["content-type"] == "application/pdf"
    assert cd.startswith("attachment;")
    # Quotes/Backslash/CR/LF aus dem Dateinamen entfernt.
    assert '"' not in cd.split('filename="', 1)[1].rstrip().rstrip('"')
    assert "\r" not in cd and "\n" not in cd
    assert fake.calls["invoice_file_bytes"] == _IID


# =====================================================================
# ROUTER: accounts CRUD
# =====================================================================
def test_list_accounts(fake: _FakeService) -> None:
    resp = _client(fake, ("account.manage",)).get("/api/accounts")
    assert resp.status_code == 200
    assert resp.json()[0]["iban"] == "DE00"


def test_create_account(fake: _FakeService) -> None:
    resp = _client(fake, ("account.manage",)).post(
        "/api/accounts", json={"name": "Neu"}
    )
    assert resp.status_code == 201
    assert fake.calls["create_account"] is not None


def test_update_account(fake: _FakeService) -> None:
    aid = uuid.uuid4()
    resp = _client(fake, ("account.manage",)).patch(
        f"/api/accounts/{aid}", json={"active": False}
    )
    assert resp.status_code == 200
    assert fake.calls["update_account"][0] == aid


def test_delete_account(fake: _FakeService) -> None:
    aid = uuid.uuid4()
    resp = _client(fake, ("account.manage",)).delete(f"/api/accounts/{aid}")
    assert resp.status_code == 204
    assert fake.calls["delete_account"] == aid


# =====================================================================
# SCHEMAS: model_validators (both sides of every branch)
# =====================================================================
def test_expense_create_income_not_linkable() -> None:
    # income + application_id ⇒ ValueError.
    with pytest.raises(ValueError, match="income cannot be linked"):
        ExpenseCreate(amount=Decimal("1"), description="x", kind="income", applicationId=_AID)
    # income ohne application_id ⇒ ok (Validator-Rückgabe self).
    ok = ExpenseCreate(amount=Decimal("1"), description="x", kind="income")
    assert ok.kind == "income"
    # expense + application_id ⇒ ok (erste Bedingung false).
    ok2 = ExpenseCreate(amount=Decimal("1"), description="x", applicationId=_AID)
    assert ok2.application_id == _AID


def test_expense_update_at_least_one() -> None:
    with pytest.raises(ValueError, match="at least one field required"):
        ExpenseUpdate()
    ok = ExpenseUpdate(description="neu")
    assert ok.description == "neu"


def test_invoice_update_at_least_one() -> None:
    with pytest.raises(ValueError, match="at least one field required"):
        InvoiceUpdate()
    ok = InvoiceUpdate(status="paid")
    assert ok.status == "paid"


def test_transfer_create_distinct() -> None:
    same = uuid.uuid4()
    with pytest.raises(ValueError, match="must differ"):
        TransferCreate(
            fromBudgetId=same,
            toBudgetId=same,
            fiscalYearId=_FYID,
            amount=Decimal("1"),
            description="x",
        )
    ok = TransferCreate(
        fromBudgetId=_FROM,
        toBudgetId=_TO,
        fiscalYearId=_FYID,
        amount=Decimal("1"),
        description="x",
    )
    assert ok.from_budget_id != ok.to_budget_id


# =====================================================================
# INVOICE_IMPORT: pure helpers (all branches)
# =====================================================================
def test_amount_helper() -> None:
    assert _amount(None) is None
    assert _amount(SimpleNamespace(amount=Decimal("5"))) == Decimal("5")


def test_sane_amount_helper() -> None:
    assert _sane_amount(None) is None
    assert _sane_amount(Decimal("NaN")) is None  # not finite
    assert _sane_amount(Decimal("-1")) is None  # negative
    assert _sane_amount(Decimal("99999999999.99")) is None  # too large
    assert _sane_amount(Decimal("10.00")) == Decimal("10.00")


def test_require_sane_gross() -> None:
    assert _require_sane_gross(Decimal("100.00")) == Decimal("100.00")
    with pytest.raises(NotZugferdError):
        _require_sane_gross(Decimal("NaN"))
    with pytest.raises(NotZugferdError):
        _require_sane_gross(Decimal("-1"))
    with pytest.raises(NotZugferdError):
        _require_sane_gross(Decimal("99999999999.99"))


def test_cii_date_helper() -> None:
    assert _cii_date(None) is None
    assert _cii_date("") is None
    assert _cii_date("2026") is None  # too short
    assert _cii_date("abcdefgh") is None  # non-digit prefix
    assert _cii_date("20261301") is None  # invalid month → ValueError branch
    assert _cii_date("20260613") == date(2026, 6, 13)


def test_cii_decimal_helper() -> None:
    assert _cii_decimal(None) is None
    assert _cii_decimal("not-a-number") is None
    assert _cii_decimal("12.34") == Decimal("12.34")


def test_find_text_helper() -> None:
    # el is None ⇒ None.
    assert _find_text(None, "x") is None
    root = ET.fromstring("<r><a>  </a><b>hi</b></r>")
    # found is None (kein passendes Element) ⇒ None.
    assert _find_text(root, "missing") is None
    # found.text only whitespace ⇒ None (text or None branch).
    assert _find_text(root, "a") is None
    # echter Text.
    assert _find_text(root, "b") == "hi"
    # Element ohne Text-Inhalt (self-closing) ⇒ found.text None ⇒ None.
    root2 = ET.fromstring("<r><c/></r>")
    assert _find_text(root2, "c") is None


# --- _map branches via SimpleNamespace stubs --------------------------------
def test_map_non_eur_currency() -> None:
    inv = SimpleNamespace(currency_code="USD")
    with pytest.raises(UnsupportedInvoiceCurrencyError) as ei:
        _map(inv)  # type: ignore[arg-type]
    assert ei.value.currency == "USD"


def test_map_missing_gross_is_not_zugferd() -> None:
    inv = SimpleNamespace(currency_code="EUR", grand_total_amount=None)
    with pytest.raises(NotZugferdError):
        _map(inv)  # type: ignore[arg-type]


def test_map_minimal_no_tax_no_terms_no_seller() -> None:
    """currency None→EUR default, leere taxes ⇒ tax None, terms/seller None."""
    inv = SimpleNamespace(
        currency_code=None,  # → "EUR"
        grand_total_amount=SimpleNamespace(amount=Decimal("50.00")),
        invoice_number="R-9",
        invoice_date=date(2026, 1, 1),
        # tax_total_amounts/payment_terms/seller/tax_basis_total_amount fehlen ⇒ getattr None
    )
    parsed = _map(inv)  # type: ignore[arg-type]
    assert parsed.gross_amount == Decimal("50.00")
    assert parsed.tax_amount is None
    assert parsed.due_date is None
    assert parsed.supplier is None
    assert parsed.net_amount is None
    assert parsed.currency == "EUR"


def test_map_with_tax_terms_seller() -> None:
    inv = SimpleNamespace(
        currency_code="EUR",
        grand_total_amount=SimpleNamespace(amount=Decimal("119.00")),
        invoice_number="R-1",
        invoice_date=date(2026, 6, 13),
        tax_total_amounts=[SimpleNamespace(amount=Decimal("19.00"))],
        payment_terms=SimpleNamespace(due_date=date(2026, 7, 1)),
        seller=SimpleNamespace(name="Muster GmbH"),
        tax_basis_total_amount=SimpleNamespace(amount=Decimal("100.00")),
    )
    parsed = _map(inv)  # type: ignore[arg-type]
    assert parsed.tax_amount == Decimal("19.00")
    assert parsed.due_date == date(2026, 7, 1)
    assert parsed.supplier == "Muster GmbH"
    assert parsed.net_amount == Decimal("100.00")


# --- parse_zugferd_pdf: FacturXError → tolerant CII fallback ----------------
_VALID_CII = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocument>
    <ram:ID>F-1</ram:ID>
    <ram:IssueDateTime>
      <udt:DateTimeString format="102">20260101</udt:DateTimeString>
    </ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>
        <ram:Name>Fallback GmbH</ram:Name>
      </ram:SellerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:GrandTotalAmount>200.00</ram:GrandTotalAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>"""


def _pdf_with_xml(name: str, xml: str | bytes) -> bytes:
    payload = xml.encode("utf-8") if isinstance(xml, str) else xml
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.add_attachment(name, payload)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_parse_zugferd_pdf_facturx_error_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pycheval lehnt das XML ab (FacturXError) ⇒ toleranter Header-Fallback greift."""
    import pycheval

    pdf = _pdf_with_xml("factur-x.xml", _VALID_CII)

    def _raise(_xml: str) -> Any:
        raise pycheval.FacturXError("strict reject")

    monkeypatch.setattr(pycheval, "parse_xml", _raise)
    parsed = parse_zugferd_pdf(pdf)
    assert parsed.number == "F-1"
    assert parsed.supplier == "Fallback GmbH"
    assert parsed.gross_amount == Decimal("200.00")
    assert parsed.issue_date == date(2026, 1, 1)


def test_parse_zugferd_pdf_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """pycheval akzeptiert ⇒ ``_map``-Pfad (kein Fallback)."""
    import pycheval

    pdf = _pdf_with_xml("factur-x.xml", _VALID_CII)
    sentinel = SimpleNamespace(
        currency_code="EUR",
        grand_total_amount=SimpleNamespace(amount=Decimal("200.00")),
        invoice_number="MAPPED",
        invoice_date=date(2026, 1, 1),
    )
    monkeypatch.setattr(pycheval, "parse_xml", lambda _xml: sentinel)
    parsed = parse_zugferd_pdf(pdf)
    assert parsed.number == "MAPPED"


# --- _extract_cii_xml: size / decode / content-error branches ---------------
def test_extract_unreadable_pdf() -> None:
    with pytest.raises(NotZugferdError, match="unreadable PDF"):
        _extract_cii_xml(b"not a pdf at all")


def test_extract_no_embedded_files() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(NotZugferdError, match="no embedded files"):
        _extract_cii_xml(buf.getvalue())


def test_extract_no_xml_attachment() -> None:
    pdf = _pdf_with_xml("notes.txt", b"just a note")
    with pytest.raises(NotZugferdError, match="no embedded XML"):
        _extract_cii_xml(pdf)


def test_extract_declared_size_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deklarierte ``/Size`` > Limit ⇒ NotZugferdError (line 118)."""
    pdf = _pdf_with_xml("factur-x.xml", _VALID_CII)
    real_reader = getattr(imp, "PdfReader", None)
    assert real_reader is None  # PdfReader ist lazy-importiert

    from pypdf import PdfReader as _RealReader

    class _BigEmb:
        name = "factur-x.xml"
        size = imp._MAX_EMBEDDED_XML_BYTES + 1
        content = b"<x/>"

    class _FakeReader:
        def __init__(self, _stream: Any) -> None:
            pass

        @property
        def attachment_list(self) -> list[_BigEmb]:
            return [_BigEmb()]

    monkeypatch.setattr("pypdf.PdfReader", _FakeReader)
    with pytest.raises(NotZugferdError, match="too large"):
        _extract_cii_xml(pdf)
    # Realer Reader bleibt unangetastet (sanity).
    assert _RealReader is not _FakeReader


def test_extract_content_decompress_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """``chosen.content`` wirft ⇒ NotZugferdError 'unreadable embedded XML' (121-122)."""

    class _Emb:
        name = "factur-x.xml"
        size = None

        @property
        def content(self) -> bytes:
            raise RuntimeError("decompress boom")

    class _FakeReader:
        def __init__(self, _stream: Any) -> None:
            pass

        @property
        def attachment_list(self) -> list[_Emb]:
            return [_Emb()]

    monkeypatch.setattr("pypdf.PdfReader", _FakeReader)
    with pytest.raises(NotZugferdError, match="unreadable embedded XML"):
        _extract_cii_xml(b"whatever")


def test_extract_payload_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tatsächliche Payload > Limit ⇒ NotZugferdError (line 124)."""
    big = b"<x>" + b"a" * (imp._MAX_EMBEDDED_XML_BYTES + 1) + b"</x>"

    class _Emb:
        name = "factur-x.xml"
        size = None
        content = big

    class _FakeReader:
        def __init__(self, _stream: Any) -> None:
            pass

        @property
        def attachment_list(self) -> list[_Emb]:
            return [_Emb()]

    monkeypatch.setattr("pypdf.PdfReader", _FakeReader)
    with pytest.raises(NotZugferdError, match="too large"):
        _extract_cii_xml(b"whatever")


def test_extract_invalid_utf8_uses_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ungültiges UTF-8 ⇒ decode('utf-8','replace') (line 128-129)."""
    bad = b"\xff\xfe<x/>"

    class _Emb:
        name = "factur-x.xml"
        size = None
        content = bad

    class _FakeReader:
        def __init__(self, _stream: Any) -> None:
            pass

        @property
        def attachment_list(self) -> list[_Emb]:
            return [_Emb()]

    monkeypatch.setattr("pypdf.PdfReader", _FakeReader)
    out = _extract_cii_xml(b"whatever")
    assert isinstance(out, str)
    assert "�" in out  # replacement char


# --- _parse_cii_header: tx/settlement/summation None branches ---------------
def test_parse_cii_header_minimal_gross_only() -> None:
    """Nur Gross vorhanden; tx/agreement/settlement-Unterpfade ohne Werte ⇒ Defaults."""
    xml = (
        '<rsm:CrossIndustryInvoice '
        'xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" '
        'xmlns:ram="urn:un:unece:uncefact:data:standard:'
        'ReusableAggregateBusinessInformationEntity:100" '
        'xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">'
        "<rsm:SupplyChainTradeTransaction>"
        "<ram:ApplicableHeaderTradeSettlement>"
        "<ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
        "<ram:GrandTotalAmount>5.00</ram:GrandTotalAmount>"
        "</ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
        "</ram:ApplicableHeaderTradeSettlement>"
        "</rsm:SupplyChainTradeTransaction>"
        "</rsm:CrossIndustryInvoice>"
    )
    parsed = _parse_cii_header(xml)
    assert parsed.gross_amount == Decimal("5.00")
    assert parsed.number is None
    assert parsed.supplier is None
    assert parsed.due_date is None
    assert parsed.tax_amount is None
    assert parsed.net_amount is None
    assert parsed.currency == "EUR"


def test_parse_cii_header_no_settlement_no_gross_is_not_zugferd() -> None:
    """tx vorhanden, aber keine settlement/summation ⇒ gross None ⇒ NotZugferdError."""
    xml = (
        '<rsm:CrossIndustryInvoice '
        'xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" '
        'xmlns:ram="urn:un:unece:uncefact:data:standard:'
        'ReusableAggregateBusinessInformationEntity:100">'
        "<rsm:SupplyChainTradeTransaction/>"
        "</rsm:CrossIndustryInvoice>"
    )
    with pytest.raises(NotZugferdError):
        _parse_cii_header(xml)


def test_parse_cii_header_no_tx_no_gross_is_not_zugferd() -> None:
    """Kein SupplyChainTradeTransaction ⇒ tx None ⇒ settlement None ⇒ NotZugferd."""
    xml = (
        '<rsm:CrossIndustryInvoice '
        'xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"/>'
    )
    with pytest.raises(NotZugferdError):
        _parse_cii_header(xml)


def test_parse_cii_header_unparseable_xml() -> None:
    """Kaputtes XML ⇒ ET.ParseError ⇒ NotZugferdError (line 267-268)."""
    with pytest.raises(NotZugferdError, match="unparseable CII XML"):
        _parse_cii_header(b"<rsm:CrossIndustryInvoice>not closed")


def test_parse_cii_header_non_eur_currency() -> None:
    """Währung ≠ EUR ⇒ UnsupportedInvoiceCurrencyError (line 285)."""
    xml = _VALID_CII.replace(
        "<ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>",
        "<ram:InvoiceCurrencyCode>USD</ram:InvoiceCurrencyCode>",
    )
    with pytest.raises(UnsupportedInvoiceCurrencyError) as ei:
        _parse_cii_header(xml)
    assert ei.value.currency == "USD"


def test_parse_cii_header_bytes_input() -> None:
    """Bytes-Eingang wird unverändert geparst (isinstance str-Zweig false)."""
    xml = (
        b'<rsm:CrossIndustryInvoice '
        b'xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" '
        b'xmlns:ram="urn:un:unece:uncefact:data:standard:'
        b'ReusableAggregateBusinessInformationEntity:100">'
        b"<rsm:SupplyChainTradeTransaction>"
        b"<ram:ApplicableHeaderTradeSettlement>"
        b"<ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
        b"<ram:GrandTotalAmount>7.00</ram:GrandTotalAmount>"
        b"</ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
        b"</ram:ApplicableHeaderTradeSettlement>"
        b"</rsm:SupplyChainTradeTransaction>"
        b"</rsm:CrossIndustryInvoice>"
    )
    parsed = _parse_cii_header(xml)
    assert parsed.gross_amount == Decimal("7.00")
