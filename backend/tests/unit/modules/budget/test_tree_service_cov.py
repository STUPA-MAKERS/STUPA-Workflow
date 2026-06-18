"""Branch-/Zeilen-Vollabdeckung für :mod:`app.modules.budget.tree_service`.

Kritisches Modul (testing.md §1: ``budget`` → 100 % Branch). DB-los: ein lokaler
``_Session``-Fake (Spiegel der Support-Fakes, ergänzt um ``add_all``, iterierbares
``scalars()`` und DB-Default-Nachstellung für ``ExpenseOut``/``InvoiceOut``) liefert
vorab gefüllte ``execute``-Resultate FIFO, ``get`` aus einer eigenen Queue; die zwei
Audit-``execute`` je Mutation werden übersprungen. Jeder Fehler-/Guard-/Leer-/None-
Pfad wird einzeln getroffen.

Ergänzt ``test_budget_tree_service_unit`` um die dort nicht berührten Methoden
(Expenses, Accounts, Invoices, Transfer, ZUGFeRD-Import, ``can_view_node``,
``list_applications``, ``_rename_key``, Suche/Paging, ``_actor_names``) sowie die
verbleibenden ``get_tree``-Zweige (fully_bound, remaining≤0, Gremium-Scope).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.budget import tree_service as ts_mod
from app.modules.budget.invoice_import import ParsedInvoice
from app.modules.budget.tree_models import (
    Account,
    Budget,
    BudgetAllocation,
    BudgetExpense,
    FiscalYear,
    Invoice,
)
from app.modules.budget.tree_schemas import (
    AccountCreate,
    AccountUpdate,
    BudgetNodeUpdate,
    ExpenseCreate,
    ExpenseUpdate,
    FiscalYearCreate,
    InvoiceCreate,
    InvoiceUpdate,
    TransferCreate,
)
from app.modules.budget.tree_service import (
    BudgetTreeService,
    _natural_path_key,
    _validate_invoice_file_token,
)
from app.modules.files.mime import MimeRejected
from app.modules.files.scanner import ScannerError, ScanVerdict
from app.modules.files.storage import StorageError
from app.settings import Settings
from app.shared.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
    ValidationProblem,
)


# --------------------------------------------------------------- local fakes
# Eigene Session/Result-Fakes (die Support-Fakes haben weder ``add_all``, noch ein
# iterierbares ``scalars()``, noch das DB-``created_at``/``id``-Default-Verhalten,
# das ``ExpenseOut``/``InvoiceOut`` brauchen). Reine Test-Hilfen, kein Support-Edit.
class _R:
    """Minimaler ``Result``: FIFO-Items, iterierbar, ``scalars()``/``all()``/``first()``."""

    def __init__(self, *items: Any) -> None:
        self._items = list(items)

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None

    def scalars(self) -> _R:
        return self

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any:
        return self._items[0] if self._items else None

    def __iter__(self) -> Any:
        return iter(self._items)


class _Session:
    """``AsyncSession``-Stub: ``execute``/``scalar`` ziehen FIFO aus EINER Queue,
    ``get`` aus einer eigenen. ``add``/``add_all`` vergeben DB-Defaults (id/created_at)."""

    def __init__(self, results: list[_R], gets: list[Any]) -> None:
        self._results = list(results)
        self._gets = list(gets)
        self.bind = None  # → dialect_of liefert 'postgresql' (Such-Pfad)
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.flushed = 0
        self.committed = 0

    @staticmethod
    def _is_audit_stmt(stmt: Any) -> bool:
        # Der Audit-Trail (audit_record) feuert pro Mutation 2 ``execute`` (Advisory-Lock
        # + prev_hash-Select auf ``audit_entry``). Diese überspringen wir, damit die
        # Test-Queue nur die fachlichen Service-Queries spiegelt (Idiom wie im Bestand).
        text = str(stmt).lower()
        return "pg_advisory_xact_lock" in text or "audit_entry" in text

    async def execute(self, stmt: Any) -> _R:
        if self._is_audit_stmt(stmt):
            return _R()
        return self._results.pop(0) if self._results else _R()

    async def scalars(self, _stmt: Any) -> _R:
        return self._results.pop(0) if self._results else _R()

    async def scalar(self, _stmt: Any) -> Any:
        return (await self.execute(_stmt)).scalar_one_or_none()

    async def get(self, _model: Any, _ident: Any) -> Any:
        return self._gets.pop(0) if self._gets else None

    def _assign_defaults(self, obj: Any) -> None:
        # DB-Server-Defaults nachstellen (kein refresh in der Fake-Session):
        # id (gen_random_uuid), created_at (now), currency (EUR-CHECK).
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        if hasattr(obj, "currency") and getattr(obj, "currency", None) is None:
            obj.currency = "EUR"

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        self._assign_defaults(obj)

    def add_all(self, objs: Any) -> None:
        for o in objs:
            self.add(o)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flushed += 1
        for obj in self.added:
            self._assign_defaults(obj)

    async def commit(self) -> None:
        self.committed += 1


def result(*items: Any) -> _R:
    return _R(*items)


def fake_session(*results: _R, gets: list[Any] | None = None) -> Any:
    return _Session(list(results), list(gets or []))


# ----------------------------------------------------------------- factories
def _budget(  # noqa: ANN001
    *, id=None, parent_id=None, path_key="VS", gremium_id=None, key="VS", name="N",
    currency="EUR", fiscal_start_month=1, fiscal_start_day=1, fully_bound=False,
    view_gremium_id=None, accepted=None, denied=None,
):
    b = Budget(
        parent_id=parent_id, gremium_id=gremium_id, key=key,
        path_key=path_key, name=name, currency=currency, active=True,
        fiscal_start_month=fiscal_start_month, fiscal_start_day=fiscal_start_day,
        fully_bound=fully_bound, view_gremium_id=view_gremium_id,
    )
    b.id = id or uuid.uuid4()
    b.accepted_state_keys = accepted or []
    b.denied_state_keys = denied or []
    return b


def _fy(*, id=None, budget_id=None, year=2026, active=True):  # noqa: ANN001
    f = FiscalYear(
        budget_id=budget_id, year=year,
        start_date=date(year, 1, 1), end_date=date(year, 12, 31), active=active,
    )
    f.id = id or uuid.uuid4()
    return f


def _alloc(*, budget_id, fy_id, allocated):  # noqa: ANN001
    a = BudgetAllocation(budget_id=budget_id, fiscal_year_id=fy_id, allocated=Decimal(allocated))
    a.id = uuid.uuid4()
    return a


def _app(*, id=None, budget_id=None, fiscal_year_id=None, amount=None, data=None):  # noqa: ANN001
    a = Application(
        type_id=uuid.uuid4(), form_version_id=uuid.uuid4(), flow_version_id=uuid.uuid4(),
        budget_id=budget_id, fiscal_year_id=fiscal_year_id, amount=amount,
        data=data if data is not None else {},
    )
    a.id = id or uuid.uuid4()
    return a


def _expense(  # noqa: ANN001
    *, id=None, budget_id=None, fy_id=None, kind="expense", amount="10.00",
    application_id=None, account_id=None, invoice_id=None, transfer_id=None,
    actor=None, currency="EUR",
):
    e = BudgetExpense(
        budget_id=budget_id or uuid.uuid4(),
        fiscal_year_id=fy_id or uuid.uuid4(),
        application_id=application_id, account_id=account_id, invoice_id=invoice_id,
        transfer_id=transfer_id, kind=kind, amount=Decimal(amount), currency=currency,
        description="x", actor=actor,
    )
    e.id = id or uuid.uuid4()
    e.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    return e


def _account(*, id=None, name="Hauptkonto", iban="DE00", active=True):  # noqa: ANN001
    a = Account(name=name, iban=iban, active=active)
    a.id = id or uuid.uuid4()
    return a


def _invoice(*, id=None, number="R-1", gross="119.00", file_key=None,  # noqa: ANN001
             file_name=None, file_mime=None):
    inv = Invoice(number=number, gross_amount=Decimal(gross), currency="EUR", status="open")
    inv.id = id or uuid.uuid4()
    inv.file_object_key = file_key
    inv.file_name = file_name
    inv.file_mime = file_mime
    inv.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    return inv


def _pg_session(*results: Any) -> Any:
    """Alias für ``fake_session`` (``bind=None`` → ``dialect_of`` = 'postgresql', Such-Pfad)."""
    return fake_session(*results)


def _settings(**over: Any) -> Settings:
    base = {
        "attachment_max_bytes": 1024,
        "clamav_host": None,
        "environment": "development",
    }
    base.update(over)
    return Settings(**base)


# ----------------------------------------------------------- helper functions
def test_natural_path_key_numeric_vs_string() -> None:
    # Numerische Segmente als (0, int), nicht-numerische als (1, str): VSM-9 < VSM-10.
    assert _natural_path_key("VSM-9") < _natural_path_key("VSM-10")
    assert _natural_path_key("VS") < _natural_path_key("VS-800")


def test_validate_invoice_file_token_ok() -> None:
    assert _validate_invoice_file_token("invoices/abc/file.pdf") == "invoices/abc/file.pdf"


def test_validate_invoice_file_token_bad_prefix() -> None:
    with pytest.raises(ValidationProblem):
        _validate_invoice_file_token("evil/x.pdf")


def test_validate_invoice_file_token_traversal() -> None:
    with pytest.raises(ValidationProblem):
        _validate_invoice_file_token("invoices/../secret.pdf")


# ------------------------------------------------------------------ _rename_key
async def test_update_node_rename_key_top_level() -> None:
    # Key-Wechsel am Top-Level → path_key neu, Nachfahren angepasst (kein Parent-Lookup).
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    child = _budget(id=uuid.uuid4(), parent_id=node.id, path_key="VS-800", key="800")
    # _get_node(node), _sibling_exists(None), descendants
    sess = fake_session(result(node), result(), result(child))
    svc = BudgetTreeService(sess)
    out = await svc.update_node(node.id, _node_update(key="VV"))
    assert out.key == "VV" and out.path_key == "VV"
    assert child.path_key == "VV-800"


def _node_update(**kw: Any) -> BudgetNodeUpdate:
    return BudgetNodeUpdate(**kw)


async def test_update_node_rename_key_child_with_parent_lookup() -> None:
    parent = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), parent_id=parent.id, path_key="VS-800", key="800")
    # _get_node(node), _sibling_exists(None→use ==), _get_node(parent), descendants(none)
    sess = fake_session(result(node), result(), result(parent), result())
    svc = BudgetTreeService(sess)
    out = await svc.update_node(node.id, _node_update(key="900"))
    assert out.key == "900" and out.path_key == "VS-900"


async def test_update_node_rename_key_invalid() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    sess = fake_session(result(node))  # _get_node only; invalid key raises before sibling-check
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.update_node(node.id, _node_update(key="bad-key"))


async def test_update_node_rename_key_conflict() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    other = _budget(id=uuid.uuid4(), path_key="VV", key="VV")
    sess = fake_session(result(node), result(other))  # sibling exists → conflict
    svc = BudgetTreeService(sess)
    from app.shared.errors import ConflictError

    with pytest.raises(ConflictError):
        await svc.update_node(node.id, _node_update(key="VV"))


async def test_update_node_rename_key_same_value_noop() -> None:
    # new_key == node.key → _rename_key wird NICHT aufgerufen (Branch new_key != node.key).
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    sess = fake_session(result(node))
    svc = BudgetTreeService(sess)
    out = await svc.update_node(node.id, _node_update(key="VS", name="Neu"))
    assert out.key == "VS" and out.name == "Neu"


async def test_update_node_stichtag_changed_but_not_top_level() -> None:
    # Stichtag geändert, aber Knoten hat Parent → kein HHJ-Rederive (Branch parent_id None).
    parent_id = uuid.uuid4()
    node = _budget(id=uuid.uuid4(), parent_id=parent_id, path_key="VS-800", key="800",
                   fiscal_start_month=1)
    sess = fake_session(result(node))  # only _get_node; no _fiscal_years_of call
    svc = BudgetTreeService(sess)
    out = await svc.update_node(node.id, _node_update(fiscalStartMonth=7))
    assert out.fiscal_start_month == 7


# ------------------------------------------------------------ _fiscal_year_bounds
async def test_create_fiscal_year_impossible_stichtag_raises_422() -> None:
    # Altbestand/Direkter Aufruf mit unmöglichem Stichtag (31.02.) → der Service
    # wrappt das ValueError aus ``fiscal_year_bounds`` zu einem 422 statt 500 (#sec-audit).
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS",
                  fiscal_start_month=2, fiscal_start_day=31)
    sess = fake_session(result(top))  # _require_top_level only; raises vor Dublettencheck
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))


# ------------------------------------------------------------ _require_top_level
async def test_require_top_level_rejects_child() -> None:
    child = _budget(id=uuid.uuid4(), parent_id=uuid.uuid4(), path_key="VS-800", key="800")
    sess = fake_session(result(child))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.create_fiscal_year(child.id, FiscalYearCreate(year=2026))


# --------------------------------------------------------------- can_view_node
async def test_can_view_node_empty_member_set() -> None:
    svc = BudgetTreeService(fake_session())
    assert await svc.can_view_node(uuid.uuid4(), set()) is False


async def test_can_view_node_match_on_ancestor() -> None:
    g = uuid.uuid4()
    node = _budget(id=uuid.uuid4(), path_key="VS-800-04", key="04")
    # rows = view_gremium_id der Pfad-Präfixe: VS trägt g (Vorfahr-Treffer), Rest None.
    sess = fake_session(result(node), result(g, None, None))
    svc = BudgetTreeService(sess)
    assert await svc.can_view_node(node.id, {g}) is True


async def test_can_view_node_no_match() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    sess = fake_session(result(node), result(None))  # only None view_gremium_ids
    svc = BudgetTreeService(sess)
    assert await svc.can_view_node(node.id, {uuid.uuid4()}) is False


# ----------------------------------------------------------- fiscal_year_label_map
async def test_fiscal_year_label_map() -> None:
    fid1, fid2 = uuid.uuid4(), uuid.uuid4()
    sess = fake_session(result((fid1, 2026, 1, 1), (fid2, 2026, 7, 1)))
    svc = BudgetTreeService(sess)
    out = await svc.fiscal_year_label_map()
    assert out[fid1] == "2026"
    assert out[fid2] == "2026/27"


# --------------------------------------------------------------- list_applications
async def test_list_applications_with_fiscal_year_filter() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    fy_id = uuid.uuid4()
    app = _app(budget_id=node.id, fiscal_year_id=fy_id, amount=Decimal("100"),
               data={"title": "Antrag X"})
    app.current_state_id = uuid.uuid4()
    app.currency = "EUR"
    app.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    row = (app, "VS", "review", {"de": "In Prüfung"}, "#abc")
    # _get_node, rows
    sess = fake_session(result(node), result(row))
    svc = BudgetTreeService(sess)
    out = await svc.list_applications(node.id, fiscal_year_id=fy_id)
    assert len(out) == 1
    assert out[0].title == "Antrag X"
    assert out[0].state_label == {"de": "In Prüfung"}
    assert out[0].stage == "review"


async def test_list_applications_no_filter_empty_state_label() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    app = _app(budget_id=node.id, fiscal_year_id=uuid.uuid4(), amount=Decimal("50"))
    app.current_state_id = None
    app.currency = "EUR"
    app.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    # state_label falsy ("" or None) → state_label or None == None
    row = (app, "VS", None, None, None)
    sess = fake_session(result(node), result(row))
    svc = BudgetTreeService(sess)
    out = await svc.list_applications(node.id)
    assert out[0].state_label is None
    assert out[0].stage is None


# ------------------------------------------------------------------- expenses
async def test_book_expense_standalone_with_account_and_actor() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    acc = _account(id=uuid.uuid4(), name="Bank")
    # _actor_names selektiert Tupel (sub, display_name, email).
    # _get_node(payload.budget), _resolve_fy: _top_level + _fiscal_years_of,
    # _validate_account via session.get(Account), then _actor_names
    sess = fake_session(
        result(node),                 # _get_node(payload.budget_id)
        result(top),                  # _top_level
        result(fy),                   # _fiscal_years_of
        result(("u-1", "Alice", "a@x")),  # _actor_names
        gets=[acc],                   # session.get(Account, ...)
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(
        amount=Decimal("42.00"), description="Rechnung", budgetId=node.id,
        accountId=acc.id,
    )
    out = await svc.book_expense(payload, actor="u-1")
    assert out.amount == Decimal("42.00")
    assert out.account_name == "Bank"
    assert out.actor_name == "Alice"   # display_name aufgelöst


async def test_create_expense_compat_wraps_budget_id() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    sess = fake_session(
        result(node), result(top), result(fy), result(),  # last: _actor_names (empty)
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(amount=Decimal("5.00"), description="d", fiscalYearId=fy.id)
    out = await svc.create_expense(node.id, payload, actor="anon")
    assert out.budget_id == node.id
    # actor gesetzt, aber kein Principal-Treffer → actor_name None
    assert out.actor == "anon"
    assert out.actor_name is None


async def test_book_expense_linked_to_application() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    fy_id = uuid.uuid4()
    app = _app(budget_id=node.id, fiscal_year_id=fy_id, data={"title": "Linked"})
    # session.get(Application) → app, then _get_node(app.budget_id) → node,
    # then _validate_account(None)→None, then _actor_names
    sess = fake_session(
        result(node),       # _get_node(app.budget_id)
        result(),           # _actor_names (no actor row)
        gets=[app],         # session.get(Application)
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(
        amount=Decimal("10.00"), description="d", applicationId=app.id,
    )
    out = await svc.book_expense(payload, actor="")
    assert out.application_title == "Linked"
    assert out.fiscal_year_id == fy_id


async def test_book_expense_linked_application_not_found() -> None:
    sess = fake_session(gets=[None])  # session.get(Application) → None
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(amount=Decimal("1.00"), description="d",
                            applicationId=uuid.uuid4())
    with pytest.raises(NotFoundError):
        await svc.book_expense(payload, actor="a")


async def test_book_expense_marks_open_invoice_paid() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    inv = _invoice(id=uuid.uuid4())  # status='open'
    sess = fake_session(
        result(node), result(top), result(fy), result(),  # _actor_names empty
        gets=[inv],  # _mark_invoice_paid → session.get(Invoice)
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(
        amount=Decimal("10.00"), description="d", budgetId=node.id, invoiceId=inv.id,
    )
    out = await svc.book_expense(payload, actor="")
    assert out.amount == Decimal("10.00")
    assert inv.status == "paid"  # offen → bezahlt beim Buchen


async def test_book_expense_already_paid_invoice_is_noop() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    inv = _invoice(id=uuid.uuid4())
    inv.status = "paid"  # bereits bezahlt → No-op (kein erneuter Status-Wechsel)
    sess = fake_session(
        result(node), result(top), result(fy), result(),
        gets=[inv],
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(
        amount=Decimal("10.00"), description="d", budgetId=node.id, invoiceId=inv.id,
    )
    await svc.book_expense(payload, actor="")
    assert inv.status == "paid"


async def test_book_expense_unknown_invoice_404() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    sess = fake_session(
        result(node), result(top), result(fy),
        gets=[None],  # session.get(Invoice) → None
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(
        amount=Decimal("1.00"), description="d", budgetId=node.id, invoiceId=uuid.uuid4(),
    )
    with pytest.raises(NotFoundError):
        await svc.book_expense(payload, actor="")


async def test_book_expense_linked_application_unassigned() -> None:
    app = _app(budget_id=None, fiscal_year_id=None)
    sess = fake_session(gets=[app])
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(amount=Decimal("1.00"), description="d", applicationId=app.id)
    with pytest.raises(ValidationProblem):
        await svc.book_expense(payload, actor="a")


async def test_book_expense_standalone_missing_budget_id() -> None:
    svc = BudgetTreeService(fake_session())
    payload = ExpenseCreate(amount=Decimal("1.00"), description="d")
    with pytest.raises(ValidationProblem):
        await svc.book_expense(payload, actor="a")


# ------------------------------------------------------------- _validate_account
async def test_validate_account_not_found() -> None:
    sess = fake_session(gets=[None])  # session.get(Account) → None
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc._validate_account(uuid.uuid4())


async def test_validate_account_none_returns_none() -> None:
    svc = BudgetTreeService(fake_session())
    assert await svc._validate_account(None) is None


# --------------------------------------------------------------- update_expense
async def test_update_expense_all_fields_with_app_and_account() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    app = _app(budget_id=node.id, data={"title": "T"})
    acc = _account(id=uuid.uuid4(), name="Konto")
    inv = _invoice(id=uuid.uuid4())  # offen → wird beim Verknüpfen auf bezahlt gesetzt
    expense = _expense(budget_id=node.id, application_id=app.id, account_id=acc.id,
                       actor="u-1")
    # gets: BudgetExpense, Account(validate in account_id branch), Invoice(mark paid),
    #   then after commit: _get_node(execute), Application(get), Account(get),
    #   _actor_names(execute)
    sess = fake_session(
        result(node),                     # _get_node(expense.budget_id) after commit
        result(("u-1", None, "bob@x")),   # _actor_names → display_name None → email
        gets=[expense, acc, inv, app, acc],
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseUpdate(
        amount=Decimal("99.00"), description="neu", accountId=acc.id,
        invoiceDate=date(2026, 1, 2), paymentDate=date(2026, 1, 3),
        correspondent="ACME", note="n", referenceNumber="R9",
        paymentMethod="bar", category="Reise", invoiceId=inv.id,
    )
    out = await svc.update_expense(expense.id, payload)
    assert out.amount == Decimal("99.00")
    assert out.account_name == "Konto"
    assert out.application_title == "T"
    assert out.actor_name == "bob@x"   # display_name None → email
    assert inv.status == "paid"        # verknüpfte Rechnung → bezahlt


async def test_update_expense_clears_account_no_app() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    expense = _expense(budget_id=node.id, application_id=None, account_id=None, actor=None)
    # account_id set to None in payload → _validate_account(None) returns None (no get)
    sess = fake_session(
        result(node),   # _get_node after commit
        result(),       # _actor_names (no actor)
        gets=[expense],
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseUpdate(accountId=None, note=None)
    out = await svc.update_expense(expense.id, payload)
    assert out.account_id is None
    assert out.account_name is None
    assert out.application_title is None


async def test_update_expense_amount_none_skipped() -> None:
    # "amount" gesetzt aber None → Branch payload.amount is not None == False.
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    expense = _expense(budget_id=node.id, amount="7.00")
    sess = fake_session(result(node), result(), gets=[expense])
    svc = BudgetTreeService(sess)
    # description set so model passes _at_least_one; amount stays 7
    payload = ExpenseUpdate(description="d2")
    out = await svc.update_expense(expense.id, payload)
    assert out.amount == Decimal("7.00")
    assert out.description == "d2"


async def test_update_expense_rebooks_cost_centre() -> None:
    # Kostenstelle einer eigenständigen Buchung umbuchen (#25): budget_id + Währung
    # folgen dem neuen Knoten; HHJ bleibt fix.
    old = _budget(id=uuid.uuid4(), path_key="VS-1", key="1")
    new = _budget(id=uuid.uuid4(), path_key="VS-2", key="2", currency="EUR")
    expense = _expense(budget_id=old.id, application_id=None, account_id=None, actor=None)
    sess = fake_session(
        result(new),   # _get_node(payload.budget_id) im budget_id-Branch
        result(new),   # _get_node(expense.budget_id) nach commit (Pfad)
        result(),      # _actor_names (kein actor)
        gets=[expense],
    )
    svc = BudgetTreeService(sess)
    out = await svc.update_expense(expense.id, ExpenseUpdate(budgetId=new.id))
    assert out.budget_id == new.id
    assert out.path_key == "VS-2"
    assert expense.currency == "EUR"


async def test_update_expense_rebook_unknown_budget_404() -> None:
    # Ziel-Kostenstelle existiert nicht → 404 (kein FK-Crash beim Commit).
    expense = _expense(budget_id=uuid.uuid4(), application_id=None, account_id=None)
    sess = fake_session(result(), gets=[expense])  # _get_node → None → NotFoundError
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.update_expense(expense.id, ExpenseUpdate(budgetId=uuid.uuid4()))


async def test_update_expense_clears_invoice_link_no_mark() -> None:
    # "invoice_id" gesetzt, aber None → Verknüpfung gelöst, kein Invoice-Lookup/-Flip
    # (Branch ``payload.invoice_id is not None`` == False).
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    expense = _expense(budget_id=node.id, invoice_id=uuid.uuid4())
    sess = fake_session(result(node), result(), gets=[expense])  # nur get(BudgetExpense)
    svc = BudgetTreeService(sess)
    payload = ExpenseUpdate(invoiceId=None)
    out = await svc.update_expense(expense.id, payload)
    assert out.invoice_id is None


async def test_update_expense_app_missing_after_commit() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    expense = _expense(budget_id=node.id, application_id=uuid.uuid4())
    # session.get(Application) → None → app_title None branch
    sess = fake_session(result(node), result(), gets=[expense, None])
    svc = BudgetTreeService(sess)
    out = await svc.update_expense(expense.id, ExpenseUpdate(description="d"))
    assert out.application_title is None


async def test_update_expense_account_deleted_concurrently() -> None:
    # #race: ``account_id`` gesetzt, aber paralleles delete_account (FK SET NULL) → der
    # Re-Read ``session.get(Account)`` nach Commit liefert None → acc_name None statt 500.
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    acc = _account(id=uuid.uuid4(), name="Konto")
    expense = _expense(budget_id=node.id, application_id=None, account_id=acc.id, actor=None)
    # Nur ``description`` im Payload → kein ``_validate_account``-Get. Nach Commit liest
    # ``session.get(Account)`` die (zwischenzeitlich gelöschte) Zeile → None.
    sess = fake_session(
        result(node),   # _get_node nach Commit
        result(),       # _actor_names (kein actor)
        gets=[expense, None],
    )
    svc = BudgetTreeService(sess)
    out = await svc.update_expense(expense.id, ExpenseUpdate(description="d"))
    assert out.account_name is None


async def test_update_expense_not_found() -> None:
    sess = fake_session(gets=[None])
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.update_expense(uuid.uuid4(), ExpenseUpdate(description="x"))


# --------------------------------------------------------------- list_expenses
async def test_list_expenses_compat_delegates() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    e = _expense(budget_id=node.id, actor="u-1")
    # list_expenses_paged: _get_node, count(scalar via execute), rows, _actor_names
    sess = fake_session(
        result(node),
        result(3),                                          # count
        result((e, "VS", {"title": "AppT"}, "Konto", "INV-1")),  # rows
        result(("u-1", "Carol", None)),                     # _actor_names
    )
    svc = BudgetTreeService(sess)
    out = await svc.list_expenses(node.id)
    assert len(out) == 1
    assert out[0].application_title == "AppT"
    assert out[0].account_name == "Konto"
    assert out[0].invoice_number == "INV-1"
    assert out[0].actor_name == "Carol"


async def test_list_expenses_paged_no_filters_empty() -> None:
    # budget_id None → kein _get_node; total None → 0; keine Zeilen.
    sess = fake_session(result(None), result())  # count None, rows empty
    svc = BudgetTreeService(sess)
    page = await svc.list_expenses_paged()
    assert page.total == 0
    assert page.items == []


async def test_list_expenses_paged_all_filters_and_search() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    e = _expense(budget_id=node.id, actor=None)
    # _get_node, count, rows, _actor_names(none since actor None → empty set → {} )
    sess = _pg_session(
        result(node),
        result(1),
        result((e, "VS", None, None, None)),  # data None → title None branch
    )
    svc = BudgetTreeService(sess)
    page = await svc.list_expenses_paged(
        budget_id=node.id, fiscal_year_id=uuid.uuid4(), kind="expense",
        application_id=uuid.uuid4(), q="rechnung", amount_min=Decimal("1"),
        amount_max=Decimal("100"), created_from="2026-01-01", created_to="2026-12-31",
        sort="invoiceDate", order="asc", limit=10, offset=0,
    )
    assert page.total == 1
    assert page.items[0].application_title is None


async def test_list_expenses_paged_blank_query_no_rank() -> None:
    # q whitespace only → kein Trigram-Pfad (rank_expr None), sort='amount', order desc.
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    e = _expense(budget_id=node.id, actor="u-9")
    sess = fake_session(
        result(node), result(0), result((e, "VS", None, None, None)), result(),
    )
    svc = BudgetTreeService(sess)
    page = await svc.list_expenses_paged(budget_id=node.id, q="   ", sort="amount",
                                         order="desc")
    assert page.total == 0   # total None? no, 0 → Page total 0
    assert len(page.items) == 1


async def test_list_expenses_paged_sort_payment_date_default_order() -> None:
    # sort='paymentDate' → nulls_last branch; order None → desc default.
    sess = fake_session(result(0), result())
    svc = BudgetTreeService(sess)
    page = await svc.list_expenses_paged(sort="paymentDate")
    assert page.total == 0


# --------------------------------------------------------------- delete_expense
async def test_delete_expense_simple() -> None:
    e = _expense(transfer_id=None)
    sess = fake_session(result(e))
    svc = BudgetTreeService(sess)
    await svc.delete_expense(e.id)
    assert sess.deleted == [e]
    assert sess.committed == 1


async def test_delete_expense_transfer_pair() -> None:
    tid = uuid.uuid4()
    e = _expense(transfer_id=tid)
    pair_a = _expense(transfer_id=tid, kind="expense")
    pair_b = _expense(transfer_id=tid, kind="income")
    sess = fake_session(result(e), result(pair_a, pair_b))  # find expense, then pair
    svc = BudgetTreeService(sess)
    await svc.delete_expense(e.id)
    assert sess.deleted == [pair_a, pair_b]


# --------------------------------------------------------------- accounts
async def test_list_accounts() -> None:
    a1, a2 = _account(name="A"), _account(name="B")
    sess = fake_session(result(a1, a2))
    svc = BudgetTreeService(sess)
    out = await svc.list_accounts()
    assert [a.name for a in out] == ["A", "B"]
    assert out[0].iban == "DE00"


async def test_list_account_options() -> None:
    a1 = _account(name="Aktiv")
    sess = fake_session(result(a1))
    svc = BudgetTreeService(sess)
    out = await svc.list_account_options()
    assert out[0].name == "Aktiv"
    assert not hasattr(out[0], "iban") or "iban" not in out[0].model_dump()


async def test_create_account() -> None:
    sess = fake_session()
    svc = BudgetTreeService(sess)
    out = await svc.create_account(AccountCreate(name="Neu", iban="DE99"))
    assert out.name == "Neu" and out.iban == "DE99"
    assert sess.committed == 1


async def test_update_account_ok() -> None:
    acc = _account(id=uuid.uuid4(), name="Alt")
    sess = fake_session(gets=[acc])
    svc = BudgetTreeService(sess)
    out = await svc.update_account(acc.id, AccountUpdate(name="Neu", active=False))
    assert out.name == "Neu" and out.active is False


async def test_update_account_not_found() -> None:
    sess = fake_session(gets=[None])
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.update_account(uuid.uuid4(), AccountUpdate(name="x"))


async def test_delete_account_ok() -> None:
    acc = _account(id=uuid.uuid4())
    sess = fake_session(gets=[acc])
    svc = BudgetTreeService(sess)
    await svc.delete_account(acc.id)
    assert sess.deleted == [acc]


async def test_delete_account_not_found() -> None:
    sess = fake_session(gets=[None])
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.delete_account(uuid.uuid4())


# --------------------------------------------------------------- invoices
async def test_list_invoices_compat() -> None:
    inv = _invoice(file_key="invoices/x/a.pdf", file_name="a.pdf")
    sess = fake_session(result(0), result(inv))  # count, rows
    svc = BudgetTreeService(sess)
    out = await svc.list_invoices()
    assert len(out) == 1
    assert out[0].has_file is True   # file_object_key set


async def test_list_invoices_paged_all_filters_and_search() -> None:
    inv = _invoice()
    sess = _pg_session(result(2), result(inv))  # count, rows
    svc = BudgetTreeService(sess)
    page = await svc.list_invoices_paged(
        q="acme", status="open", gross_min=Decimal("1"), gross_max=Decimal("999"),
        issue_from="2026-01-01", issue_to="2026-12-31",
        due_from="2026-01-01", due_to="2026-12-31", limit=20, offset=0,
    )
    assert page.total == 2
    assert page.items[0].has_file is False


async def test_list_invoices_paged_no_search_blank_q() -> None:
    sess = fake_session(result(None), result())  # count None → 0, no rows
    svc = BudgetTreeService(sess)
    page = await svc.list_invoices_paged(q="")
    assert page.total == 0


async def test_get_invoice_ok() -> None:
    inv = _invoice()
    sess = fake_session(gets=[inv])
    svc = BudgetTreeService(sess)
    out = await svc.get_invoice(inv.id)
    assert out.number == "R-1"


async def test_get_invoice_not_found() -> None:
    sess = fake_session(gets=[None])
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.get_invoice(uuid.uuid4())


async def test_create_invoice_without_file() -> None:
    sess = fake_session()
    svc = BudgetTreeService(sess)
    out = await svc.create_invoice(
        InvoiceCreate(number="R-2", grossAmount=Decimal("50.00")), actor="u"
    )
    assert out.number == "R-2"
    # create_invoice flusht für die id (+ audit_record flusht); commit genau einmal.
    assert sess.flushed >= 1 and sess.committed == 1


async def test_create_invoice_with_file_token() -> None:
    sess = fake_session()
    svc = BudgetTreeService(sess)
    out = await svc.create_invoice(
        InvoiceCreate(
            number="R-3", grossAmount=Decimal("10.00"),
            fileToken="invoices/x/a.pdf", fileName="a.pdf", fileMime="application/pdf",
        ),
        actor="u",
    )
    assert out.has_file is True
    assert out.file_name == "a.pdf"


async def test_create_invoice_with_invalid_file_token() -> None:
    sess = fake_session()
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.create_invoice(
            InvoiceCreate(number="R", grossAmount=Decimal("1"), fileToken="evil/x"),
            actor="u",
        )


async def test_update_invoice_all_fields() -> None:
    inv = _invoice()
    sess = fake_session(gets=[inv])
    svc = BudgetTreeService(sess)
    out = await svc.update_invoice(
        inv.id,
        InvoiceUpdate(
            number="R-9", issueDate=date(2026, 1, 1), dueDate=date(2026, 2, 1),
            supplier="ACME", netAmount=Decimal("100"), taxAmount=Decimal("19"),
            grossAmount=Decimal("119"), note="n", status="paid",
        ),
    )
    assert out.number == "R-9"
    assert out.status == "paid"


async def test_update_invoice_gross_and_status_none_skipped() -> None:
    # gross_amount/status NICHT in fields → ``in fields``-Kurzschluss False; nur ``note``
    # gesetzt → ``supplier``-Branch (1413) auf der False-Seite (kein Wert geschrieben).
    inv = _invoice(gross="119.00")
    sess = fake_session(gets=[inv])
    svc = BudgetTreeService(sess)
    out = await svc.update_invoice(inv.id, InvoiceUpdate(note="nur Notiz"))
    assert out.note == "nur Notiz"
    assert out.gross_amount == Decimal("119.00")


async def test_update_invoice_gross_and_status_explicit_none() -> None:
    # gross_amount/status explizit None → ``... and payload.X is not None`` False-Seite.
    inv = _invoice(gross="119.00")
    sess = fake_session(gets=[inv])
    svc = BudgetTreeService(sess)
    out = await svc.update_invoice(
        inv.id, InvoiceUpdate(supplier="S", grossAmount=None, status=None)
    )
    assert out.supplier == "S"
    assert out.gross_amount == Decimal("119.00")  # unverändert
    assert out.status == "open"


async def test_update_invoice_not_found() -> None:
    sess = fake_session(gets=[None])
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.update_invoice(uuid.uuid4(), InvoiceUpdate(note="x"))


async def test_delete_invoice_no_file() -> None:
    inv = _invoice(file_key=None)
    sess = fake_session(gets=[inv])
    svc = BudgetTreeService(sess)
    await svc.delete_invoice(inv.id)
    assert sess.deleted == [inv]


async def test_delete_invoice_with_file_storage_removes() -> None:
    inv = _invoice(file_key="invoices/x/a.pdf")
    sess = fake_session(gets=[inv])
    removed: list[str] = []

    class _Storage:
        async def put(self, *a: Any) -> None: ...
        async def get(self, k: str) -> bytes:
            return b""
        async def remove(self, key: str) -> None:
            removed.append(key)

    svc = BudgetTreeService(sess, storage=cast("Any", _Storage()))
    await svc.delete_invoice(inv.id)
    assert removed == ["invoices/x/a.pdf"]


async def test_delete_invoice_storage_remove_error_is_swallowed() -> None:
    inv = _invoice(file_key="invoices/x/a.pdf")
    sess = fake_session(gets=[inv])

    class _Storage:
        async def put(self, *a: Any) -> None: ...
        async def get(self, k: str) -> bytes:
            return b""
        async def remove(self, key: str) -> None:
            raise StorageError("gone")

    svc = BudgetTreeService(sess, storage=cast("Any", _Storage()))
    await svc.delete_invoice(inv.id)  # error logged, not raised
    assert sess.committed == 1


async def test_delete_invoice_with_file_but_no_storage() -> None:
    # storage None → kein remove-Versuch (Branch storage is not None == False).
    inv = _invoice(file_key="invoices/x/a.pdf")
    sess = fake_session(gets=[inv])
    svc = BudgetTreeService(sess, storage=None)
    await svc.delete_invoice(inv.id)
    assert sess.committed == 1


async def test_delete_invoice_not_found() -> None:
    sess = fake_session(gets=[None])
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.delete_invoice(uuid.uuid4())


# --------------------------------------------------- _invoice_number_exists
async def test_invoice_number_exists_true() -> None:
    sess = fake_session(result(uuid.uuid4()))  # scalars → first not None
    svc = BudgetTreeService(sess)
    assert await svc._invoice_number_exists("R-1") is True


async def test_invoice_number_exists_false_empty() -> None:
    sess = fake_session(result())
    svc = BudgetTreeService(sess)
    assert await svc._invoice_number_exists("R-1") is False


async def test_invoice_number_exists_none() -> None:
    svc = BudgetTreeService(fake_session())
    assert await svc._invoice_number_exists(None) is False


# --------------------------------------------------- invoice_file_bytes
async def test_invoice_file_bytes_ok() -> None:
    inv = _invoice(file_key="invoices/x/a.pdf", file_name="a.pdf", file_mime="application/pdf")
    sess = fake_session(gets=[inv])

    class _Storage:
        async def put(self, *a: Any) -> None: ...
        async def get(self, key: str) -> bytes:
            return b"PDFDATA"
        async def remove(self, key: str) -> None: ...

    svc = BudgetTreeService(sess, storage=cast("Any", _Storage()))
    data, mime, name = await svc.invoice_file_bytes(inv.id)
    assert data == b"PDFDATA" and mime == "application/pdf" and name == "a.pdf"


async def test_invoice_file_bytes_defaults_mime_name() -> None:
    inv = _invoice(file_key="invoices/x/a.pdf", file_name=None, file_mime=None)
    sess = fake_session(gets=[inv])

    class _Storage:
        async def put(self, *a: Any) -> None: ...
        async def get(self, key: str) -> bytes:
            return b"X"
        async def remove(self, key: str) -> None: ...

    svc = BudgetTreeService(sess, storage=cast("Any", _Storage()))
    data, mime, name = await svc.invoice_file_bytes(inv.id)
    assert mime == "application/pdf" and name == "beleg.pdf"


async def test_invoice_file_bytes_invoice_not_found() -> None:
    sess = fake_session(gets=[None])
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.invoice_file_bytes(uuid.uuid4())


async def test_invoice_file_bytes_no_stored_file() -> None:
    inv = _invoice(file_key=None)
    sess = fake_session(gets=[inv])
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.invoice_file_bytes(inv.id)


async def test_invoice_file_bytes_no_storage() -> None:
    inv = _invoice(file_key="invoices/x/a.pdf")
    sess = fake_session(gets=[inv])
    svc = BudgetTreeService(sess, storage=None)
    with pytest.raises(ServiceUnavailableError):
        await svc.invoice_file_bytes(inv.id)


async def test_invoice_file_bytes_storage_error() -> None:
    inv = _invoice(file_key="invoices/x/a.pdf")
    sess = fake_session(gets=[inv])

    class _Storage:
        async def put(self, *a: Any) -> None: ...
        async def get(self, key: str) -> bytes:
            raise StorageError("io")
        async def remove(self, key: str) -> None: ...

    svc = BudgetTreeService(sess, storage=cast("Any", _Storage()))
    with pytest.raises(ServiceUnavailableError):
        await svc.invoice_file_bytes(inv.id)


# ----------------------------------------------------- _validate_scan_store
def _ok_storage(store: list[Any] | None = None) -> Any:
    class _Storage:
        async def put(self, key: str, data: bytes, mime: str) -> None:
            if store is not None:
                store.append((key, data, mime))

        async def get(self, key: str) -> bytes:
            return b""

        async def remove(self, key: str) -> None: ...

    return _Storage()


async def test_store_invoice_file_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ts_mod, "validate_upload", lambda fn, data: "application/pdf")
    monkeypatch.setattr(ts_mod, "sanitize_filename", lambda fn: "safe.pdf")
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    res = await svc.store_invoice_file(b"%PDF-1.4", filename="beleg.pdf")
    assert res.file_name == "safe.pdf"
    assert res.file_mime == "application/pdf"
    assert res.file_token.startswith("invoices/")


async def test_validate_scan_store_too_large() -> None:
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(),
                            settings=_settings(attachment_max_bytes=2))
    with pytest.raises(PayloadTooLargeError):
        await svc._validate_scan_store(b"123456", filename="x.pdf")


async def test_validate_scan_store_empty() -> None:
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc._validate_scan_store(b"", filename="x.pdf")


async def test_validate_scan_store_mime_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def _reject(fn: Any, data: Any) -> str:
        raise MimeRejected("nope")

    monkeypatch.setattr(ts_mod, "validate_upload", _reject)
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc._validate_scan_store(b"data", filename="x.pdf")


async def test_validate_scan_store_not_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ts_mod, "validate_upload", lambda fn, data: "image/png")
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc._validate_scan_store(b"data", filename="x.png")


# --------------------------------------------------------- _scan_or_raise
async def test_scan_skipped_when_no_scanner_dev() -> None:
    # build_scanner None + environment != production → skip (no raise).
    svc = BudgetTreeService(fake_session(), settings=_settings(environment="development"))
    await svc._scan_or_raise(b"data")  # no exception


async def test_scan_no_scanner_production_fails_closed() -> None:
    svc = BudgetTreeService(fake_session(), settings=_settings(environment="production"))
    with pytest.raises(ServiceUnavailableError):
        await svc._scan_or_raise(b"data")


async def test_scan_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Scanner:
        async def scan(self, data: bytes) -> ScanVerdict:
            return ScanVerdict(clean=True)

    monkeypatch.setattr(ts_mod, "build_scanner", lambda s: _Scanner())
    svc = BudgetTreeService(fake_session(), settings=_settings())
    await svc._scan_or_raise(b"data")  # clean → no raise


async def test_scan_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Scanner:
        async def scan(self, data: bytes) -> ScanVerdict:
            raise ScannerError("down")

    monkeypatch.setattr(ts_mod, "build_scanner", lambda s: _Scanner())
    svc = BudgetTreeService(fake_session(), settings=_settings())
    with pytest.raises(ServiceUnavailableError):
        await svc._scan_or_raise(b"data")


async def test_scan_infected_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Scanner:
        async def scan(self, data: bytes) -> ScanVerdict:
            return ScanVerdict(clean=False, signature="EICAR")

    monkeypatch.setattr(ts_mod, "build_scanner", lambda s: _Scanner())
    svc = BudgetTreeService(fake_session(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc._scan_or_raise(b"data")


async def test_scan_infected_unknown_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Scanner:
        async def scan(self, data: bytes) -> ScanVerdict:
            return ScanVerdict(clean=False, signature=None)

    monkeypatch.setattr(ts_mod, "build_scanner", lambda s: _Scanner())
    svc = BudgetTreeService(fake_session(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc._scan_or_raise(b"data")


# --------------------------------------------------------- _store_invoice_file
async def test_store_invoice_file_no_storage() -> None:
    svc = BudgetTreeService(fake_session(), storage=None, settings=_settings())
    with pytest.raises(ServiceUnavailableError):
        await svc._store_invoice_file(b"x", "application/pdf", "a.pdf")


async def test_store_invoice_file_put_error() -> None:
    class _Storage:
        async def put(self, *a: Any) -> None:
            raise StorageError("write")

        async def get(self, key: str) -> bytes:
            return b""

        async def remove(self, key: str) -> None: ...

    svc = BudgetTreeService(fake_session(), storage=cast("Any", _Storage()), settings=_settings())
    with pytest.raises(ServiceUnavailableError):
        await svc._store_invoice_file(b"x", "application/pdf", "a.pdf")


# --------------------------------------------------------- parse_invoice_file
async def test_parse_invoice_file_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ts_mod, "validate_upload", lambda fn, data: "application/pdf")
    monkeypatch.setattr(ts_mod, "sanitize_filename", lambda fn: "safe.pdf")
    parsed = ParsedInvoice(
        number="R-100", issue_date=date(2026, 1, 1), due_date=date(2026, 2, 1),
        supplier="ACME", net_amount=Decimal("100"), tax_amount=Decimal("19"),
        gross_amount=Decimal("119"), currency="EUR",
    )
    monkeypatch.setattr(ts_mod, "parse_zugferd_pdf", lambda data: parsed)
    # _invoice_number_exists → existing scalars empty (no dup)
    sess = fake_session(result())
    svc = BudgetTreeService(sess, storage=_ok_storage(), settings=_settings())
    res = await svc.parse_invoice_file(b"%PDF-1.4", filename="r.pdf")
    assert res.number == "R-100"
    assert res.gross_amount == Decimal("119")
    assert res.file_token.startswith("invoices/")
    assert res.duplicate is False


async def test_parse_invoice_file_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ts_mod, "validate_upload", lambda fn, data: "application/pdf")
    monkeypatch.setattr(ts_mod, "sanitize_filename", lambda fn: "safe.pdf")
    parsed = ParsedInvoice(
        number="DUP", issue_date=None, due_date=None, supplier=None,
        net_amount=None, tax_amount=None, gross_amount=Decimal("5"), currency="EUR",
    )
    monkeypatch.setattr(ts_mod, "parse_zugferd_pdf", lambda data: parsed)
    sess = fake_session(result(uuid.uuid4()))  # dup found
    svc = BudgetTreeService(sess, storage=_ok_storage(), settings=_settings())
    res = await svc.parse_invoice_file(b"%PDF-1.4", filename="r.pdf")
    assert res.duplicate is True


async def test_parse_invoice_file_too_large() -> None:
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(),
                            settings=_settings(attachment_max_bytes=2))
    with pytest.raises(PayloadTooLargeError):
        await svc.parse_invoice_file(b"123456", filename="r.pdf")


async def test_parse_invoice_file_empty() -> None:
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc.parse_invoice_file(b"", filename="r.pdf")


async def test_parse_invoice_file_mime_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def _reject(fn: Any, data: Any) -> str:
        raise MimeRejected("nope")

    monkeypatch.setattr(ts_mod, "validate_upload", _reject)
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc.parse_invoice_file(b"data", filename="r.pdf")


async def test_parse_invoice_file_not_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ts_mod, "validate_upload", lambda fn, data: "image/png")
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc.parse_invoice_file(b"data", filename="r.png")


# --------------------------------------------------------------- transfer
async def test_create_transfer_ok() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    src = _budget(id=uuid.uuid4(), parent_id=top.id, path_key="VS-1", key="1", currency="EUR")
    dst = _budget(id=uuid.uuid4(), parent_id=top.id, path_key="VS-2", key="2", currency="EUR")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
    # _get_node(src), _get_node(dst),
    # _resolve_fy(src): _top_level(src)→top, _get_fiscal_year(fy)
    # _resolve_fy(dst): _top_level(dst)→top, _get_fiscal_year(fy)
    sess = fake_session(
        result(src), result(dst),
        result(top), result(fy),
        result(top), result(fy),
    )
    svc = BudgetTreeService(sess)
    out = await svc.create_transfer(
        TransferCreate(
            fromBudgetId=src.id, toBudgetId=dst.id, fiscalYearId=fy.id,
            amount=Decimal("100"), description="Umbuchung",
        ),
        actor="u",
    )
    assert out.expense_id is not None and out.income_id is not None
    booked = [o for o in sess.added if isinstance(o, BudgetExpense)]
    assert len(booked) == 2


async def test_create_transfer_fy_mismatch() -> None:
    top1 = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top2 = _budget(id=uuid.uuid4(), path_key="VV", key="VV")
    src = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    dst = _budget(id=uuid.uuid4(), path_key="VV", key="VV")
    fy1 = _fy(id=uuid.uuid4(), budget_id=top1.id)
    fy2 = _fy(id=uuid.uuid4(), budget_id=top2.id)
    # src resolves to fy1 (explicit, belongs to top1); dst explicit fy must belong to top2.
    # We pass fiscalYearId for both = a value; resolve returns differing ids → mismatch.
    # To force fy_src != fy_dst, give each _resolve a different explicit fy.
    # src: _top_level(src)=top1, _get_fiscal_year(fy1)
    # dst: _top_level(dst)=top2, _get_fiscal_year(fy2) but fy2.budget != top2? must match top.
    # Easier: make both explicit but return different fy ids — both must pass top-check.
    sess = fake_session(
        result(src), result(dst),
        result(top1), result(fy1),
        result(top2), result(fy2),
    )
    svc = BudgetTreeService(sess)
    # payload fiscal_year_id is fy1.id but resolve uses _get_fiscal_year queue → returns fy1/fy2
    with pytest.raises(ValidationProblem):
        await svc.create_transfer(
            TransferCreate(
                fromBudgetId=src.id, toBudgetId=dst.id, fiscalYearId=fy1.id,
                amount=Decimal("10"), description="d",
            ),
            actor="u",
        )


# --------------------------------------------------------------- _actor_names
async def test_actor_names_empty_set() -> None:
    svc = BudgetTreeService(fake_session())
    assert await svc._actor_names(set()) == {}


async def test_actor_names_filters_blank_and_resolves() -> None:
    p1 = PrincipalRow(sub="a", display_name="Anna", email=None)
    p2 = PrincipalRow(sub="b", display_name=None, email="b@x")
    sess = fake_session(result((p1.sub, p1.display_name, p1.email),
                               (p2.sub, p2.display_name, p2.email)))
    svc = BudgetTreeService(sess)
    out = await svc._actor_names({"a", "b", ""})
    assert out == {"a": "Anna", "b": "b@x"}


async def test_actor_names_fallback_to_sub() -> None:
    # display_name None + email None → fallback to sub.
    sess = fake_session(result(("c", None, None)))
    svc = BudgetTreeService(sess)
    out = await svc._actor_names({"c"})
    assert out == {"c": "c"}


# --------------------------------------------------------------- get_tree branches
async def test_get_tree_fully_bound_injects_allocation() -> None:
    """fully_bound: echte Anträge/Ausgaben unter dem Knoten ignoriert, Zuteilung als
    gebunden injiziert (Zeilen 1577-1584, 1614-1618)."""
    fy_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS", fully_bound=True,
                  accepted=["approved"])
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    # app under flagged node → ignored; expense under flagged node → ignored
    app_row = (uuid.uuid4(), "VS", fy_id, Decimal("250"), "approved")
    exp_row = ("VS", fy_id, Decimal("60"), "expense", None)
    sess = fake_session(
        result(top), result(alloc), result(app_row), result(exp_row),
    )
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.bound == Decimal("1000")     # ganze Zuteilung injiziert
    assert view.expended == Decimal("0")     # echte Ausgabe ignoriert
    assert view.available == Decimal("0")


async def test_get_tree_accepted_remaining_nonpositive_skipped() -> None:
    """accepted app, aber Ausgaben ≥ Betrag → remaining ≤ 0 → kein bound_row
    (Branch 1590->1582)."""
    fy_id = uuid.uuid4()
    app_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS", accepted=["approved"])
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    app_row = (app_id, "VS", fy_id, Decimal("100"), "approved")
    exp_row = ("VS", fy_id, Decimal("100"), "expense", app_id)  # fully spent
    sess = fake_session(result(top), result(alloc), result(app_row), result(exp_row))
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.bound == Decimal("0")        # remaining 0 → nicht gebunden
    assert view.expended == Decimal("100")


async def test_get_tree_requested_remaining_nonpositive_skipped() -> None:
    """in-flight app, Ausgaben ≥ Betrag → remaining ≤ 0 → kein requested_row
    (Branch 1599->1582)."""
    fy_id = uuid.uuid4()
    app_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")  # no accepted/denied
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="500")
    app_row = (app_id, "VS", fy_id, Decimal("80"), "submitted")  # in-flight
    exp_row = ("VS", fy_id, Decimal("80"), "expense", app_id)
    sess = fake_session(result(top), result(alloc), result(app_row), result(exp_row))
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.requested == Decimal("0")
    assert view.expended == Decimal("80")


async def test_get_tree_denied_excluded() -> None:
    fy_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS", denied=["rejected"])
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    app_row = (uuid.uuid4(), "VS", fy_id, Decimal("999"), "rejected")
    sess = fake_session(result(top), result(alloc), result(app_row), result())
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.bound == Decimal("0")
    assert view.requested == Decimal("0")


async def test_get_tree_fully_bound_zero_allocation_not_injected() -> None:
    # fully_bound but allocation 0/None → not injected (Branch a.allocated falsy at 1617).
    fy_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS", fully_bound=True)
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="0")
    sess = fake_session(result(top), result(alloc), result(), result())
    svc = BudgetTreeService(sess)
    tree = await svc.get_tree()
    # allocation 0 → either no view or bound 0
    views = tree[0].by_fiscal_year
    if views:
        assert views[0].bound == Decimal("0")


async def test_get_tree_with_gremium_scope() -> None:
    """visible_gremium_ids gesetzt → scope_forest (Zeile 1653-1654)."""
    g = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS", view_gremium_id=g)
    sess = fake_session(result(top), result(), result(), result())
    svc = BudgetTreeService(sess)
    tree = await svc.get_tree(visible_gremium_ids={g})
    assert len(tree) == 1
    assert tree[0].path_key == "VS"


async def test_get_tree_gremium_scope_no_match_empty() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS", view_gremium_id=uuid.uuid4())
    sess = fake_session(result(top), result(), result(), result())
    svc = BudgetTreeService(sess)
    tree = await svc.get_tree(visible_gremium_ids={uuid.uuid4()})
    assert tree == []


# --------------------------------------------------------------- audit actor
async def test_audit_uses_actor() -> None:
    # actor gesetzt → _audit ruft audit_record mit dem sub (Konstruktor-Zweig actor).
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    sess = fake_session(result(node), result(), result())  # node, no child, no alloc
    svc = BudgetTreeService(sess, actor="admin-sub")
    await svc.delete_node(node.id)
    assert sess.committed == 1


# --------------------------------------------------------------------------- #
# Audit-Log-Revert (#config-versioning): revert_audit + Helfer (DB-los)
# --------------------------------------------------------------------------- #
def _entry(
    action: AuditAction, target_id: Any, data: dict | None = None, *, eid: int = 1
) -> AuditEntry:
    """Minimaler Audit-Eintrag (revert_audit liest nur action/target_id/data/id)."""
    return cast(
        AuditEntry,
        SimpleNamespace(id=eid, action=action, target_id=str(target_id), data=data or {}),
    )


class _AsyncStub:
    """Async-Aufrufrekorder zum Monkeypatchen wiederverwendeter Mutatoren."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


# --- Buchung (budget_expense_create) -------------------------------------- #
async def test_revert_expense_create_already_reverted() -> None:
    svc = BudgetTreeService(fake_session(gets=[None]), actor="admin")
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_CREATE, uuid.uuid4()), "admin")
    assert ei.value.code == "already_reverted"


async def test_revert_expense_create_no_invoice_deletes() -> None:
    exp = _expense(id=uuid.uuid4(), invoice_id=None)
    sess = fake_session(gets=[exp])
    svc = BudgetTreeService(sess, actor="admin")
    await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_CREATE, exp.id), "admin")
    assert exp in sess.deleted and sess.committed == 1


async def test_revert_expense_create_reopens_paid_invoice() -> None:
    inv = _invoice()
    inv.status = "paid"
    exp = _expense(id=uuid.uuid4(), invoice_id=inv.id)
    sess = fake_session(gets=[exp, inv])
    svc = BudgetTreeService(sess, actor="admin")
    await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_CREATE, exp.id), "admin")
    assert inv.status == "open"
    assert exp in sess.deleted and sess.committed == 1


async def test_revert_expense_create_invoice_missing_skips_reopen() -> None:
    exp = _expense(id=uuid.uuid4(), invoice_id=uuid.uuid4())
    sess = fake_session(gets=[exp, None])  # Rechnung nicht (mehr) vorhanden
    svc = BudgetTreeService(sess, actor="admin")
    await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_CREATE, exp.id), "admin")
    assert exp in sess.deleted


async def test_revert_expense_create_invoice_not_paid_unchanged() -> None:
    inv = _invoice()  # status="open"
    exp = _expense(id=uuid.uuid4(), invoice_id=inv.id)
    sess = fake_session(gets=[exp, inv])
    svc = BudgetTreeService(sess, actor="admin")
    await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_CREATE, exp.id), "admin")
    assert inv.status == "open" and exp in sess.deleted


# --- Umbuchung (budget_transfer_create) ----------------------------------- #
async def test_revert_transfer_create_deletes_both_rows() -> None:
    tid = uuid.uuid4()
    r1 = _expense(transfer_id=tid)
    r2 = _expense(transfer_id=tid)
    sess = fake_session(result(r1, r2))  # select … where transfer_id → scalars().all()
    svc = BudgetTreeService(sess, actor="admin")
    await svc.revert_audit(_entry(AuditAction.BUDGET_TRANSFER_CREATE, tid), "admin")
    assert r1 in sess.deleted and r2 in sess.deleted and sess.committed == 1


async def test_revert_transfer_create_already_reverted() -> None:
    sess = fake_session(result())  # keine Zeilen mehr
    svc = BudgetTreeService(sess, actor="admin")
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_TRANSFER_CREATE, uuid.uuid4()), "admin")
    assert ei.value.code == "already_reverted"


# --- Kostenstelle anlegen (budget_node_create) ---------------------------- #
async def test_revert_node_create_already_reverted() -> None:
    svc = BudgetTreeService(fake_session(gets=[None]), actor="admin")
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_NODE_CREATE, uuid.uuid4()), "admin")
    assert ei.value.code == "already_reverted"


async def test_revert_node_create_delegates_to_delete_node() -> None:
    node = _budget(id=uuid.uuid4())
    svc = BudgetTreeService(fake_session(gets=[node]), actor="admin")
    stub = _AsyncStub()
    svc.delete_node = stub  # type: ignore[method-assign]
    await svc.revert_audit(_entry(AuditAction.BUDGET_NODE_CREATE, node.id), "admin")
    assert stub.calls and stub.calls[0][0][0] == node.id


# --- Kostenstelle ändern (budget_node_update) ----------------------------- #
async def test_revert_node_update_not_revertable_without_before() -> None:
    svc = BudgetTreeService(fake_session(), actor="admin")
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(
            _entry(AuditAction.BUDGET_NODE_UPDATE, uuid.uuid4(), {}), "admin"
        )
    assert ei.value.code == "not_revertable"


async def test_revert_node_update_already_reverted() -> None:
    svc = BudgetTreeService(fake_session(gets=[None]), actor="admin")
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(
            _entry(AuditAction.BUDGET_NODE_UPDATE, uuid.uuid4(), {"before": {"name": "X"}}),
            "admin",
        )
    assert ei.value.code == "already_reverted"


async def test_revert_node_update_stale_when_after_mismatch() -> None:
    node = _budget(id=uuid.uuid4(), name="Aktuell")
    svc = BudgetTreeService(fake_session(gets=[node]), actor="admin")
    data = {"before": {"name": "Alt"}, "after": {"name": "Anders"}}
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_NODE_UPDATE, node.id, data), "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_node_update_restores_via_update_node() -> None:
    node = _budget(id=uuid.uuid4(), name="Neu")
    svc = BudgetTreeService(fake_session(gets=[node]), actor="admin")
    stub = _AsyncStub()
    svc.update_node = stub  # type: ignore[method-assign]
    data = {"before": {"name": "Alt"}, "after": {"name": "Neu"}}  # nicht stale
    await svc.revert_audit(_entry(AuditAction.BUDGET_NODE_UPDATE, node.id, data), "admin")
    assert stub.calls and stub.calls[0][0][1].name == "Alt"


async def test_revert_node_update_no_after_is_best_effort() -> None:
    node = _budget(id=uuid.uuid4(), name="X")
    svc = BudgetTreeService(fake_session(gets=[node]), actor="admin")
    stub = _AsyncStub()
    svc.update_node = stub  # type: ignore[method-assign]
    data = {"before": {"name": "Alt"}}  # kein after → kein Stale-Check
    await svc.revert_audit(_entry(AuditAction.BUDGET_NODE_UPDATE, node.id, data), "admin")
    assert stub.calls


# --- Zuteilung (budget_allocation_set) ------------------------------------ #
async def test_revert_allocation_not_revertable_without_fy() -> None:
    svc = BudgetTreeService(fake_session(), actor="admin")
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(
            _entry(AuditAction.BUDGET_ALLOCATION_SET, uuid.uuid4(), {"allocated": "5"}),
            "admin",
        )
    assert ei.value.code == "not_revertable"


async def test_revert_allocation_stale_when_row_missing() -> None:
    bid, fy = uuid.uuid4(), uuid.uuid4()
    svc = BudgetTreeService(fake_session(result()), actor="admin")  # _allocation → None
    data = {"fiscalYearId": str(fy), "allocated": "100"}
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_ALLOCATION_SET, bid, data), "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_allocation_stale_when_set_value_absent() -> None:
    bid, fy = uuid.uuid4(), uuid.uuid4()
    alloc = _alloc(budget_id=bid, fy_id=fy, allocated="100")
    svc = BudgetTreeService(fake_session(result(alloc)), actor="admin")
    data = {"fiscalYearId": str(fy)}  # kein allocated → set_value None → stale
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_ALLOCATION_SET, bid, data), "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_allocation_stale_when_value_changed() -> None:
    bid, fy = uuid.uuid4(), uuid.uuid4()
    alloc = _alloc(budget_id=bid, fy_id=fy, allocated="200")
    svc = BudgetTreeService(fake_session(result(alloc)), actor="admin")
    data = {"fiscalYearId": str(fy), "allocated": "100"}  # cur 200 ≠ 100 → stale
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_ALLOCATION_SET, bid, data), "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_allocation_removes_row_when_no_previous() -> None:
    bid, fy = uuid.uuid4(), uuid.uuid4()
    alloc = _alloc(budget_id=bid, fy_id=fy, allocated="100")
    sess = fake_session(result(alloc))
    svc = BudgetTreeService(sess, actor="admin")
    data = {"fiscalYearId": str(fy), "allocated": "100", "previousAllocated": None}
    await svc.revert_audit(_entry(AuditAction.BUDGET_ALLOCATION_SET, bid, data), "admin")
    assert alloc in sess.deleted and sess.committed == 1


async def test_revert_allocation_restores_previous_via_set_allocation() -> None:
    bid, fy = uuid.uuid4(), uuid.uuid4()
    alloc = _alloc(budget_id=bid, fy_id=fy, allocated="100")
    svc = BudgetTreeService(fake_session(result(alloc)), actor="admin")
    stub = _AsyncStub()
    svc.set_allocation = stub  # type: ignore[method-assign]
    data = {"fiscalYearId": str(fy), "allocated": "100", "previousAllocated": "50"}
    await svc.revert_audit(_entry(AuditAction.BUDGET_ALLOCATION_SET, bid, data), "admin")
    assert stub.calls and stub.calls[0][0][2].allocated == Decimal("50")


# --- Buchung ändern (budget_expense_update) ------------------------------- #
async def test_revert_expense_update_not_revertable_without_before() -> None:
    svc = BudgetTreeService(fake_session(), actor="admin")
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(
            _entry(AuditAction.BUDGET_EXPENSE_UPDATE, uuid.uuid4(), {}), "admin"
        )
    assert ei.value.code == "not_revertable"


async def test_revert_expense_update_already_reverted() -> None:
    svc = BudgetTreeService(fake_session(gets=[None]), actor="admin")
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(
            _entry(
                AuditAction.BUDGET_EXPENSE_UPDATE, uuid.uuid4(), {"before": {"amount": "50"}}
            ),
            "admin",
        )
    assert ei.value.code == "already_reverted"


async def test_revert_expense_update_stale_when_amount_changed() -> None:
    exp = _expense(id=uuid.uuid4(), amount="90.00")
    svc = BudgetTreeService(fake_session(gets=[exp]), actor="admin")
    data = {"before": {"amount": "50"}, "after": {"amount": "70"}}  # 90 ≠ 70 → stale
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_UPDATE, exp.id, data), "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_expense_update_restores_decimal_tolerant() -> None:
    # after "70" vs current "70.00": wertgleich (DB-Skalierung) → nicht stale.
    exp = _expense(id=uuid.uuid4(), amount="70.00")
    svc = BudgetTreeService(fake_session(gets=[exp]), actor="admin")
    stub = _AsyncStub()
    svc.update_expense = stub  # type: ignore[method-assign]
    data = {"before": {"amount": "50"}, "after": {"amount": "70"}}
    await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_UPDATE, exp.id, data), "admin")
    assert stub.calls and stub.calls[0][0][1].amount == Decimal("50")


async def test_revert_expense_update_no_after_is_best_effort() -> None:
    exp = _expense(id=uuid.uuid4(), amount="50")
    svc = BudgetTreeService(fake_session(gets=[exp]), actor="admin")
    stub = _AsyncStub()
    svc.update_expense = stub  # type: ignore[method-assign]
    data = {"before": {"amount": "50"}}  # kein after
    await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_UPDATE, exp.id, data), "admin")
    assert stub.calls
