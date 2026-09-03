"""Full branch and line coverage for `app.modules.budget.tree`.

The module is critical (testing.md section 1: `budget` needs 100 % branch coverage).
These tests run without a database. A local `_Session` fake mirrors the support fakes.
It adds `add_all`, an iterable `scalars()` and the DB defaults that `ExpenseOut` and
`InvoiceOut` need. It returns prefilled `execute` results FIFO and serves `get` from a
second queue. It skips the two audit `execute` calls of every mutation. Each error,
guard, empty and None path gets its own test.

This file adds the methods that `test_budget_tree_service_unit` does not touch:
expenses, invoices, transfer, ZUGFeRD import, `can_view_node`,
`list_applications`, `_rename_key`, search and paging, and `_actor_names`. It also
covers the remaining `get_tree` branches (remaining <= 0 and Gremium scope).
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
from app.modules.budget.invoice_import import ParsedInvoice
from app.modules.budget.tree import invoices as invoices_mod
from app.modules.budget.tree.invoices import _validate_invoice_file_token
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree.view import _natural_path_key
from app.modules.budget.tree_models import (
    Budget,
    BudgetAllocation,
    BudgetExpense,
    FiscalYear,
    Invoice,
)
from app.modules.budget.tree_schemas import (
    BudgetNodeUpdate,
    ExpenseCreate,
    ExpenseUpdate,
    FiscalYearCreate,
    InvoiceCreate,
    InvoiceUpdate,
    SubBookingCreate,
    TransferCreate,
    TransferUpdate,
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


class _R:
    """Minimal `Result` stub: FIFO items, iterable, `scalars()`/`all()`/`first()`."""

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
    """Stub of `AsyncSession` with two independent result queues.

    `execute` and `scalar` pull FIFO from one queue. `get` pulls from its own queue.
    `add` and `add_all` assign the DB defaults for `id` and `created_at`.
    """

    def __init__(self, results: list[_R], gets: list[Any]) -> None:
        self._results = list(results)
        self._gets = list(gets)
        self.bind = None  # dialect_of then reports 'postgresql' (the search path)
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.flushed = 0
        self.committed = 0

    @staticmethod
    def _is_audit_stmt(stmt: Any) -> bool:
        # The audit trail (audit_record) fires two `execute` calls per mutation: the
        # advisory lock and the prev_hash select on `audit_entry`. The stub skips both,
        # so the test queue mirrors only the domain queries of the service.
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
        # Reproduce the DB server defaults, because the fake session has no refresh:
        # id from gen_random_uuid, created_at from now, and currency from the EUR check.
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


def _budget(  # noqa: ANN001
    *, id=None, parent_id=None, path_key="VS", gremium_id=None, key="VS", name="N",
    currency="EUR", fiscal_start_month=1, fiscal_start_day=1,
    view_gremium_id=None, accepted=None, denied=None,
):
    b = Budget(
        parent_id=parent_id, gremium_id=gremium_id, key=key,
        path_key=path_key, name=name, currency=currency, active=True,
        fiscal_start_month=fiscal_start_month, fiscal_start_day=fiscal_start_day,
        view_gremium_id=view_gremium_id,
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
    application_id=None, invoice_id=None, transfer_id=None,
    actor=None, currency="EUR",
):
    e = BudgetExpense(
        budget_id=budget_id or uuid.uuid4(),
        fiscal_year_id=fy_id or uuid.uuid4(),
        application_id=application_id, invoice_id=invoice_id,
        transfer_id=transfer_id, kind=kind, amount=Decimal(amount), currency=currency,
        description="x", actor=actor,
    )
    e.id = id or uuid.uuid4()
    e.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    return e


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
    """Alias for `fake_session`: `bind=None` makes `dialect_of` report 'postgresql'."""
    return fake_session(*results)


def _settings(**over: Any) -> Settings:
    base = {
        "attachment_max_bytes": 1024,
        "clamav_host": None,
        "environment": "development",
    }
    base.update(over)
    return Settings(**base)


def test_natural_path_key_numeric_vs_string() -> None:
    # Numeric segments sort as (0, int) and other segments as (1, str): VSM-9 < VSM-10.
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


async def test_update_node_rename_key_top_level() -> None:
    # A key change at the top level rewrites path_key and every descendant. No parent
    # lookup happens.
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    child = _budget(id=uuid.uuid4(), parent_id=node.id, path_key="VS-800", key="800")
    # Queue: the node, an empty sibling check, then the descendants.
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
    # Queue: the node, an empty sibling check, the parent, then no descendants.
    sess = fake_session(result(node), result(), result(parent), result())
    svc = BudgetTreeService(sess)
    out = await svc.update_node(node.id, _node_update(key="900"))
    assert out.key == "900" and out.path_key == "VS-900"


async def test_update_node_rename_key_invalid() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    sess = fake_session(result(node))  # one result: a bad key raises before the sibling check
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.update_node(node.id, _node_update(key="bad-key"))


async def test_update_node_rename_key_conflict() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    other = _budget(id=uuid.uuid4(), path_key="VV", key="VV")
    sess = fake_session(result(node), result(other))  # a sibling exists, so conflict
    svc = BudgetTreeService(sess)
    from app.shared.errors import ConflictError

    with pytest.raises(ConflictError):
        await svc.update_node(node.id, _node_update(key="VV"))


async def test_update_node_rename_key_same_value_noop() -> None:
    # new_key == node.key, so _rename_key does not run (branch new_key != node.key).
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    sess = fake_session(result(node))
    svc = BudgetTreeService(sess)
    out = await svc.update_node(node.id, _node_update(key="VS", name="Neu"))
    assert out.key == "VS" and out.name == "Neu"


async def test_update_node_stichtag_changed_but_not_top_level() -> None:
    # The fiscal start date changed, but the node has a parent. The service then skips
    # the fiscal-year rederive (branch parent_id None).
    parent_id = uuid.uuid4()
    node = _budget(id=uuid.uuid4(), parent_id=parent_id, path_key="VS-800", key="800",
                   fiscal_start_month=1)
    sess = fake_session(result(node))  # the node only, no _fiscal_years_of call
    svc = BudgetTreeService(sess)
    out = await svc.update_node(node.id, _node_update(fiscalStartMonth=7))
    assert out.fiscal_start_month == 7


async def test_create_fiscal_year_impossible_stichtag_raises_422() -> None:
    # Legacy rows and direct calls can carry an impossible fiscal start date (February 31).
    # The service wraps the ValueError of `fiscal_year_bounds` into a 422, not a 500.
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS",
                  fiscal_start_month=2, fiscal_start_day=31)
    sess = fake_session(result(top))  # _require_top_level only, raises before the dup check
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))


async def test_require_top_level_rejects_child() -> None:
    child = _budget(id=uuid.uuid4(), parent_id=uuid.uuid4(), path_key="VS-800", key="800")
    sess = fake_session(result(child))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.create_fiscal_year(child.id, FiscalYearCreate(year=2026))


async def test_can_view_node_empty_member_set() -> None:
    svc = BudgetTreeService(fake_session())
    assert await svc.can_view_node(uuid.uuid4(), set()) is False


async def test_can_view_node_match_on_ancestor() -> None:
    g = uuid.uuid4()
    node = _budget(id=uuid.uuid4(), path_key="VS-800-04", key="04")
    # The rows hold view_gremium_id per path prefix. VS carries g, which is an ancestor
    # hit, and the other prefixes are None.
    sess = fake_session(result(node), result(g, None, None))
    svc = BudgetTreeService(sess)
    assert await svc.can_view_node(node.id, {g}) is True


async def test_can_view_node_no_match() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    sess = fake_session(result(node), result(None))  # every view_gremium_id is None
    svc = BudgetTreeService(sess)
    assert await svc.can_view_node(node.id, {uuid.uuid4()}) is False


async def test_fiscal_year_label_map() -> None:
    fid1, fid2 = uuid.uuid4(), uuid.uuid4()
    sess = fake_session(result((fid1, 2026, 1, 1), (fid2, 2026, 7, 1)))
    svc = BudgetTreeService(sess)
    out = await svc.fiscal_year_label_map()
    assert out[fid1] == "2026"
    assert out[fid2] == "2026/27"


async def test_list_applications_with_fiscal_year_filter() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    fy_id = uuid.uuid4()
    app = _app(budget_id=node.id, fiscal_year_id=fy_id, amount=Decimal("100"),
               data={"title": "Antrag X"})
    app.current_state_id = uuid.uuid4()
    app.currency = "EUR"
    app.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    row = (app, "VS", "review", {"de": "In Prüfung"}, "#abc")
    # Queue: the node, then the rows.
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
    # A falsy state_label ("" or None) maps to None.
    row = (app, "VS", None, None, None)
    sess = fake_session(result(node), result(row))
    svc = BudgetTreeService(sess)
    out = await svc.list_applications(node.id)
    assert out[0].state_label is None
    assert out[0].stage is None


async def test_book_expense_standalone_with_actor() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    # _actor_names selects tuples of sub, display_name and email.
    sess = fake_session(
        result(node),                 # _get_node for payload.budget_id
        result(top),                  # _top_level
        result(fy),                   # _fiscal_years_of
        result(("u-1", "Alice", "a@x")),  # _actor_names
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(amount=Decimal("42.00"), description="Rechnung", budgetId=node.id)
    out = await svc.book_expense(payload, actor="u-1")
    assert out.amount == Decimal("42.00")
    assert out.actor_name == "Alice"   # display_name resolved


async def test_book_expense_commit_false_defers_commit() -> None:
    # With commit=False (bank reconciliation) the service creates the booking but does
    # not commit.
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    sess = fake_session(result(node), result(top), result(fy), result())
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(
        amount=Decimal("7.00"), description="d", budgetId=node.id, fiscalYearId=fy.id
    )
    out = await svc.book_expense(payload, actor="", commit=False)
    assert out.amount == Decimal("7.00")
    assert sess.committed == 0  # the caller commits


async def test_create_expense_compat_wraps_budget_id() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    sess = fake_session(
        result(node), result(top), result(fy), result(),  # last: _actor_names, no rows
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(amount=Decimal("5.00"), description="d", fiscalYearId=fy.id)
    out = await svc.create_expense(node.id, payload, actor="anon")
    assert out.budget_id == node.id
    # The actor is set, but no principal row matches, so actor_name stays None.
    assert out.actor == "anon"
    assert out.actor_name is None


async def test_book_expense_linked_to_application() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    fy_id = uuid.uuid4()
    app = _app(budget_id=node.id, fiscal_year_id=fy_id, data={"title": "Linked"})
    # The queue serves the application from session.get, then the node lookup, then
    # _actor_names.
    sess = fake_session(
        result(node),       # _get_node for app.budget_id
        result(),           # _actor_names, no actor row
        gets=[app],         # the Application from session.get
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(
        amount=Decimal("10.00"), description="d", applicationId=app.id,
    )
    out = await svc.book_expense(payload, actor="")
    assert out.application_title == "Linked"
    assert out.fiscal_year_id == fy_id


async def test_book_expense_linked_application_not_found() -> None:
    sess = fake_session(gets=[None])  # session.get returns None for the Application
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
        result(node), result(top), result(fy), result(),  # _actor_names, no rows
        gets=[inv],  # _mark_invoice_paid loads the Invoice
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(
        amount=Decimal("10.00"), description="d", budgetId=node.id, invoiceId=inv.id,
    )
    out = await svc.book_expense(payload, actor="")
    assert out.amount == Decimal("10.00")
    assert inv.status == "paid"  # open becomes paid on booking


async def test_book_expense_already_paid_invoice_is_noop() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    inv = _invoice(id=uuid.uuid4())
    inv.status = "paid"  # already paid, so the booking changes no status
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
        gets=[None],  # session.get returns None for the Invoice
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


async def test_update_expense_all_fields_with_app() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    app = _app(budget_id=node.id, data={"title": "T"})
    inv = _invoice(id=uuid.uuid4())  # open, so the link marks it paid
    expense = _expense(budget_id=node.id, application_id=app.id, actor="u-1")
    # gets: the BudgetExpense, the Invoice to mark paid, then after the commit the
    # Application for display.
    sess = fake_session(
        result(),                         # _child_counts (#subbookings), no children
        result(node),                     # _get_node for expense.budget_id after commit
        result(("u-1", None, "bob@x")),   # _actor_names: display_name None gives email
        gets=[expense, inv, app],
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseUpdate(
        amount=Decimal("99.00"), description="neu",
        invoiceDate=date(2026, 1, 2), paymentDate=date(2026, 1, 3),
        correspondent="ACME", note="n", referenceNumber="R9",
        paymentMethod="bar", category="Reise", invoiceId=inv.id,
    )
    out = await svc.update_expense(expense.id, payload)
    assert out.amount == Decimal("99.00")
    assert out.application_title == "T"
    assert out.actor_name == "bob@x"   # display_name None gives the email
    assert inv.status == "paid"        # the linked invoice becomes paid


async def test_update_expense_no_app() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    expense = _expense(budget_id=node.id, application_id=None, actor=None)
    sess = fake_session(
        result(node),   # _get_node after the commit
        result(),       # _actor_names, no actor
        gets=[expense],
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseUpdate(note=None)
    out = await svc.update_expense(expense.id, payload)
    assert out.application_title is None


async def test_update_expense_amount_none_skipped() -> None:
    # An "amount" that is present but None takes the False side of the branch
    # `payload.amount is not None`.
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    expense = _expense(budget_id=node.id, amount="7.00")
    sess = fake_session(result(node), result(), gets=[expense])
    svc = BudgetTreeService(sess)
    # description is set, so the model passes _at_least_one and the amount stays 7
    payload = ExpenseUpdate(description="d2")
    out = await svc.update_expense(expense.id, payload)
    assert out.amount == Decimal("7.00")
    assert out.description == "d2"


async def test_update_expense_rebooks_within_same_top_level() -> None:
    # Move a standalone booking to another cost center, but only inside the same
    # top-level budget. `budget_id` and the currency follow the new node. The fixed
    # fiscal year still belongs to the top-level budget (`_resolve_fiscal_year` passes,
    # #AUD-036).
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    new = _budget(id=uuid.uuid4(), parent_id=top.id, path_key="VS-2", key="2", currency="CHF")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)  # fiscal year of the top node, no orphan
    expense = _expense(
        budget_id=uuid.uuid4(), fy_id=fy.id, application_id=None, actor=None,
    )
    sess = fake_session(
        result(new),   # _get_node for payload.budget_id in the budget_id branch
        result(top),   # _resolve_fiscal_year calls _top_level for the new node
        result(fy),    # _resolve_fiscal_year loads the fiscal year of the expense
        result(new),   # _get_node for expense.budget_id after the commit (path)
        result(),      # _actor_names, no actor
        gets=[expense],
    )
    svc = BudgetTreeService(sess)
    out = await svc.update_expense(expense.id, ExpenseUpdate(budgetId=new.id))
    assert out.budget_id == new.id
    assert out.path_key == "VS-2"
    assert expense.currency == "CHF"          # the currency follows the new cost center
    assert expense.fiscal_year_id == fy.id    # the fiscal year stays fixed


async def test_update_expense_rebook_across_top_level_rejected() -> None:
    # #AUD-036: a move into a foreign top-level cost center would orphan the fiscal year
    # that the booking keeps. That leaves a phantom row. `_resolve_fiscal_year` rejects
    # with a 422 before it writes budget_id or the currency, and before any commit.
    other_top = _budget(id=uuid.uuid4(), path_key="VV", key="VV")
    new = _budget(id=uuid.uuid4(), parent_id=other_top.id, path_key="VV-2", key="2")
    fy = _fy(id=uuid.uuid4(), budget_id=uuid.uuid4())  # fiscal year of a foreign top node
    expense = _expense(
        budget_id=uuid.uuid4(), fy_id=fy.id, application_id=None, currency="EUR",
    )
    sess = fake_session(
        result(new),        # _get_node for payload.budget_id in the budget_id branch
        result(other_top),  # _resolve_fiscal_year calls _top_level for the new node
        result(fy),         # _get_fiscal_year: fy.budget_id != other_top.id gives 422
        gets=[expense],
    )
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.update_expense(expense.id, ExpenseUpdate(budgetId=new.id))
    assert expense.budget_id != new.id   # not moved
    assert expense.currency == "EUR"     # currency unchanged
    assert sess.committed == 0           # the guard abort commits nothing


async def test_update_expense_rebook_unknown_budget_404() -> None:
    # The target cost center does not exist. The service raises a 404, so the commit
    # cannot fail on the foreign key.
    expense = _expense(budget_id=uuid.uuid4(), application_id=None)
    sess = fake_session(result(), gets=[expense])  # _get_node returns None, so NotFoundError
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.update_expense(expense.id, ExpenseUpdate(budgetId=uuid.uuid4()))


async def test_update_expense_clears_invoice_link_no_mark() -> None:
    # An "invoice_id" that is present but None clears the link. There is no invoice
    # lookup and no status flip (branch `payload.invoice_id is not None` is False).
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    expense = _expense(budget_id=node.id, invoice_id=uuid.uuid4())
    sess = fake_session(result(node), result(), gets=[expense])  # only the expense get
    svc = BudgetTreeService(sess)
    payload = ExpenseUpdate(invoiceId=None)
    out = await svc.update_expense(expense.id, payload)
    assert out.invoice_id is None


async def test_update_expense_app_missing_after_commit() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    expense = _expense(budget_id=node.id, application_id=uuid.uuid4())
    # The Application get returns None, which takes the app_title None branch.
    sess = fake_session(result(node), result(), gets=[expense, None])
    svc = BudgetTreeService(sess)
    out = await svc.update_expense(expense.id, ExpenseUpdate(description="d"))
    assert out.application_title is None


async def test_update_expense_not_found() -> None:
    sess = fake_session(gets=[None])
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.update_expense(uuid.uuid4(), ExpenseUpdate(description="x"))


async def test_list_expenses_compat_delegates() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    e = _expense(budget_id=node.id, actor="u-1")
    # list_expenses_paged: the node, the count through execute, the rows, then _actor_names
    sess = fake_session(
        result(node),
        result(3),                                          # count
        result((e, "VS", {"title": "AppT"}, "INV-1")),  # rows
        result(("u-1", "Carol", None)),                     # _actor_names
    )
    svc = BudgetTreeService(sess)
    out = await svc.list_expenses(node.id)
    assert len(out) == 1
    assert out[0].application_title == "AppT"
    assert out[0].invoice_number == "INV-1"
    assert out[0].actor_name == "Carol"


async def test_list_expenses_paged_no_filters_empty() -> None:
    # A budget_id of None skips _get_node. A total of None becomes 0. No rows come back.
    sess = fake_session(result(None), result())  # count None, rows empty
    svc = BudgetTreeService(sess)
    page = await svc.list_expenses_paged()
    assert page.total == 0
    assert page.items == []


async def test_list_expenses_paged_all_filters_and_search() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    e = _expense(budget_id=node.id, actor=None)
    # The node, the count and the rows. _actor_names gets an empty set and returns {}.
    sess = _pg_session(
        result(node),
        result(1),
        result((e, "VS", None, None)),  # data None takes the title None branch
    )
    svc = BudgetTreeService(sess)
    page = await svc.list_expenses_paged(
        budget_id=node.id, fiscal_year_id=uuid.uuid4(),
        kind="expense", application_id=uuid.uuid4(), q="rechnung",
        amount_min=Decimal("1"), amount_max=Decimal("100"), created_from="2026-01-01",
        created_to="2026-12-31", sort="invoiceDate", order="asc", limit=10, offset=0,
    )
    assert page.total == 1
    assert page.items[0].application_title is None


async def test_list_expenses_paged_exact_id_filter() -> None:
    # An expense_id takes the exact-filter branch. It serves the deeplink
    # to bookings. A budget_id of None skips _get_node.
    e = _expense(actor=None)
    sess = fake_session(result(1), result((e, "VS", None, None)))
    svc = BudgetTreeService(sess)
    page = await svc.list_expenses_paged(expense_id=e.id)
    assert page.total == 1
    assert page.items[0].id == e.id


async def test_list_expenses_paged_blank_query_no_rank() -> None:
    # A q of only whitespace skips the trigram path (rank_expr None), with sort by amount
    # and order desc.
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    e = _expense(budget_id=node.id, actor="u-9")
    sess = fake_session(
        result(node), result(0), result((e, "VS", None, None)), result(),
    )
    svc = BudgetTreeService(sess)
    page = await svc.list_expenses_paged(budget_id=node.id, q="   ", sort="amount",
                                         order="desc")
    assert page.total == 0
    assert len(page.items) == 1


async def test_list_expenses_paged_sort_payment_date_default_order() -> None:
    # A sort of 'paymentDate' takes the nulls_last branch. An order of None defaults to desc.
    sess = fake_session(result(0), result())
    svc = BudgetTreeService(sess)
    page = await svc.list_expenses_paged(sort="paymentDate")
    assert page.total == 0


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


async def test_list_invoices_compat() -> None:
    inv = _invoice(file_key="invoices/x/a.pdf", file_name="a.pdf")
    sess = fake_session(result(0), result(inv))  # count, rows
    svc = BudgetTreeService(sess)
    out = await svc.list_invoices()
    assert len(out) == 1
    assert out[0].has_file is True   # file_object_key is set


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
    sess = fake_session(result(None), result())  # a count of None becomes 0, no rows
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
    # create_invoice flushes for the id, and audit_record flushes too. It commits once.
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
    # gross_amount and status are not in fields, so the `in fields` test short-circuits
    # to False. Only `note` is set, so the `supplier` branch (1413) takes the False side
    # and writes no value.
    inv = _invoice(gross="119.00")
    sess = fake_session(gets=[inv])
    svc = BudgetTreeService(sess)
    out = await svc.update_invoice(inv.id, InvoiceUpdate(note="nur Notiz"))
    assert out.note == "nur Notiz"
    assert out.gross_amount == Decimal("119.00")


async def test_update_invoice_gross_and_status_explicit_none() -> None:
    # An explicit None for gross_amount and status takes the False side of
    # `... and payload.X is not None`.
    inv = _invoice(gross="119.00")
    sess = fake_session(gets=[inv])
    svc = BudgetTreeService(sess)
    out = await svc.update_invoice(
        inv.id, InvoiceUpdate(supplier="S", grossAmount=None, status=None)
    )
    assert out.supplier == "S"
    assert out.gross_amount == Decimal("119.00")  # unchanged
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
    # A storage of None means no remove attempt (branch storage is not None is False).
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


async def test_invoice_number_exists_true() -> None:
    sess = fake_session(result(uuid.uuid4()))  # scalars gives a first that is not None
    svc = BudgetTreeService(sess)
    assert await svc._invoice_number_exists("R-1") is True


async def test_invoice_number_exists_false_empty() -> None:
    sess = fake_session(result())
    svc = BudgetTreeService(sess)
    assert await svc._invoice_number_exists("R-1") is False


async def test_invoice_number_exists_none() -> None:
    svc = BudgetTreeService(fake_session())
    assert await svc._invoice_number_exists(None) is False


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
    monkeypatch.setattr(invoices_mod, "validate_upload", lambda fn, data: "application/pdf")
    monkeypatch.setattr(invoices_mod, "sanitize_filename", lambda fn: "safe.pdf")
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

    monkeypatch.setattr(invoices_mod, "validate_upload", _reject)
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc._validate_scan_store(b"data", filename="x.pdf")


async def test_validate_scan_store_not_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(invoices_mod, "validate_upload", lambda fn, data: "image/png")
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc._validate_scan_store(b"data", filename="x.png")


async def test_scan_skipped_when_no_scanner_dev() -> None:
    # A build_scanner of None outside production skips the scan and raises nothing.
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

    monkeypatch.setattr(invoices_mod, "build_scanner", lambda s: _Scanner())
    svc = BudgetTreeService(fake_session(), settings=_settings())
    await svc._scan_or_raise(b"data")  # a clean verdict raises nothing


async def test_scan_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Scanner:
        async def scan(self, data: bytes) -> ScanVerdict:
            raise ScannerError("down")

    monkeypatch.setattr(invoices_mod, "build_scanner", lambda s: _Scanner())
    svc = BudgetTreeService(fake_session(), settings=_settings())
    with pytest.raises(ServiceUnavailableError):
        await svc._scan_or_raise(b"data")


async def test_scan_infected_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Scanner:
        async def scan(self, data: bytes) -> ScanVerdict:
            return ScanVerdict(clean=False, signature="EICAR")

    monkeypatch.setattr(invoices_mod, "build_scanner", lambda s: _Scanner())
    svc = BudgetTreeService(fake_session(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc._scan_or_raise(b"data")


async def test_scan_infected_unknown_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Scanner:
        async def scan(self, data: bytes) -> ScanVerdict:
            return ScanVerdict(clean=False, signature=None)

    monkeypatch.setattr(invoices_mod, "build_scanner", lambda s: _Scanner())
    svc = BudgetTreeService(fake_session(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc._scan_or_raise(b"data")


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


async def test_parse_invoice_file_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(invoices_mod, "validate_upload", lambda fn, data: "application/pdf")
    monkeypatch.setattr(invoices_mod, "sanitize_filename", lambda fn: "safe.pdf")
    parsed = ParsedInvoice(
        number="R-100", issue_date=date(2026, 1, 1), due_date=date(2026, 2, 1),
        supplier="ACME", net_amount=Decimal("100"), tax_amount=Decimal("19"),
        gross_amount=Decimal("119"), currency="EUR",
    )
    monkeypatch.setattr(invoices_mod, "parse_zugferd_pdf", lambda data: parsed)
    # _invoice_number_exists finds no rows, so there is no duplicate.
    sess = fake_session(result())
    svc = BudgetTreeService(sess, storage=_ok_storage(), settings=_settings())
    res = await svc.parse_invoice_file(b"%PDF-1.4", filename="r.pdf")
    assert res.number == "R-100"
    assert res.gross_amount == Decimal("119")
    assert res.file_token.startswith("invoices/")
    assert res.duplicate is False


async def test_parse_invoice_file_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(invoices_mod, "validate_upload", lambda fn, data: "application/pdf")
    monkeypatch.setattr(invoices_mod, "sanitize_filename", lambda fn: "safe.pdf")
    parsed = ParsedInvoice(
        number="DUP", issue_date=None, due_date=None, supplier=None,
        net_amount=None, tax_amount=None, gross_amount=Decimal("5"), currency="EUR",
    )
    monkeypatch.setattr(invoices_mod, "parse_zugferd_pdf", lambda data: parsed)
    sess = fake_session(result(uuid.uuid4()))  # a duplicate exists
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

    monkeypatch.setattr(invoices_mod, "validate_upload", _reject)
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc.parse_invoice_file(b"data", filename="r.pdf")


async def test_parse_invoice_file_not_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(invoices_mod, "validate_upload", lambda fn, data: "image/png")
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    with pytest.raises(UnsupportedMediaTypeError):
        await svc.parse_invoice_file(b"data", filename="r.png")


async def test_create_transfer_ok() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    src = _budget(id=uuid.uuid4(), parent_id=top.id, path_key="VS-1", key="1", currency="EUR")
    dst = _budget(id=uuid.uuid4(), parent_id=top.id, path_key="VS-2", key="2", currency="EUR")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
    # Queue: the source node, the destination node, then for each side _top_level and
    # _get_fiscal_year.
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
    # Each side resolves to its own fiscal year: the source to fy1 and the destination to
    # fy2. Both pass the top-level check, so only the mismatch guard can reject.
    sess = fake_session(
        result(src), result(dst),
        result(top1), result(fy1),
        result(top2), result(fy2),
    )
    svc = BudgetTreeService(sess)
    # The payload names fy1, but the resolver reads the queue and returns fy1 and fy2.
    with pytest.raises(ValidationProblem):
        await svc.create_transfer(
            TransferCreate(
                fromBudgetId=src.id, toBudgetId=dst.id, fiscalYearId=fy1.id,
                amount=Decimal("10"), description="d",
            ),
            actor="u",
        )


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
    # A display_name of None and an email of None fall back to the sub.
    sess = fake_session(result(("c", None, None)))
    svc = BudgetTreeService(sess)
    out = await svc._actor_names({"c"})
    assert out == {"c": "c"}


async def test_get_tree_accepted_remaining_nonpositive_skipped() -> None:
    """Skip the bound row when an accepted application is spent in full.

    Expenses greater than or equal to the amount leave remaining <= 0 (branch
    1590->1582).
    """
    fy_id = uuid.uuid4()
    app_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS", accepted=["approved"])
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    app_row = (app_id, "VS", fy_id, Decimal("100"), "approved")
    exp_row = ("VS", fy_id, Decimal("100"), "expense", app_id)  # fully spent
    sess = fake_session(result(top), result(alloc), result(app_row), result(exp_row))
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.bound == Decimal("0")        # remaining 0 binds nothing
    assert view.expended == Decimal("100")


async def test_get_tree_requested_remaining_nonpositive_skipped() -> None:
    """Skip the requested row when an in-flight application is spent in full.

    Expenses greater than or equal to the amount leave remaining <= 0 (branch
    1599->1582).
    """
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


async def test_get_tree_with_gremium_scope() -> None:
    """Reach scope_forest with visible_gremium_ids set (lines 1653-1654)."""
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


async def test_audit_uses_actor() -> None:
    # With an actor set, _audit calls audit_record with the sub (constructor actor branch).
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    sess = fake_session(result(node), result(), result())  # node, no child, no alloc
    svc = BudgetTreeService(sess, actor="admin-sub")
    await svc.delete_node(node.id)
    assert sess.committed == 1


# Audit log revert: revert_audit and its helpers, without a DB.
def _entry(
    action: AuditAction, target_id: Any, data: dict | None = None, *, eid: int = 1
) -> AuditEntry:
    """Build a minimal audit entry: revert_audit reads only action, target_id, data, id."""
    return cast(
        AuditEntry,
        SimpleNamespace(id=eid, action=action, target_id=str(target_id), data=data or {}),
    )


class _AsyncStub:
    """Record async calls, so a test can monkeypatch a reused mutator."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


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
    sess = fake_session(gets=[exp, None])  # the invoice is gone
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


async def test_revert_transfer_create_deletes_both_rows() -> None:
    tid = uuid.uuid4()
    r1 = _expense(transfer_id=tid)
    r2 = _expense(transfer_id=tid)
    sess = fake_session(result(r1, r2))  # the select on transfer_id feeds scalars().all()
    svc = BudgetTreeService(sess, actor="admin")
    await svc.revert_audit(_entry(AuditAction.BUDGET_TRANSFER_CREATE, tid), "admin")
    assert r1 in sess.deleted and r2 in sess.deleted and sess.committed == 1


async def test_revert_transfer_create_already_reverted() -> None:
    sess = fake_session(result())  # no rows left
    svc = BudgetTreeService(sess, actor="admin")
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_TRANSFER_CREATE, uuid.uuid4()), "admin")
    assert ei.value.code == "already_reverted"


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
    data = {"before": {"name": "Alt"}, "after": {"name": "Neu"}}  # not stale
    await svc.revert_audit(_entry(AuditAction.BUDGET_NODE_UPDATE, node.id, data), "admin")
    assert stub.calls and stub.calls[0][0][1].name == "Alt"


async def test_revert_node_update_no_after_is_best_effort() -> None:
    node = _budget(id=uuid.uuid4(), name="X")
    svc = BudgetTreeService(fake_session(gets=[node]), actor="admin")
    stub = _AsyncStub()
    svc.update_node = stub  # type: ignore[method-assign]
    data = {"before": {"name": "Alt"}}  # no after, so no stale check
    await svc.revert_audit(_entry(AuditAction.BUDGET_NODE_UPDATE, node.id, data), "admin")
    assert stub.calls


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
    svc = BudgetTreeService(fake_session(result()), actor="admin")  # _allocation gives None
    data = {"fiscalYearId": str(fy), "allocated": "100"}
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_ALLOCATION_SET, bid, data), "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_allocation_stale_when_set_value_absent() -> None:
    bid, fy = uuid.uuid4(), uuid.uuid4()
    alloc = _alloc(budget_id=bid, fy_id=fy, allocated="100")
    svc = BudgetTreeService(fake_session(result(alloc)), actor="admin")
    data = {"fiscalYearId": str(fy)}  # no allocated, so set_value None and stale
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_ALLOCATION_SET, bid, data), "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_allocation_stale_when_value_changed() -> None:
    bid, fy = uuid.uuid4(), uuid.uuid4()
    alloc = _alloc(budget_id=bid, fy_id=fy, allocated="200")
    svc = BudgetTreeService(fake_session(result(alloc)), actor="admin")
    data = {"fiscalYearId": str(fy), "allocated": "100"}  # current 200 != 100, so stale
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
    data = {"before": {"amount": "50"}, "after": {"amount": "70"}}  # 90 != 70, so stale
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_UPDATE, exp.id, data), "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_expense_update_restores_decimal_tolerant() -> None:
    # The after value "70" equals the current "70.00" in value (DB scale), so not stale.
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
    data = {"before": {"amount": "50"}}  # no after
    await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_UPDATE, exp.id, data), "admin")
    assert stub.calls


async def test_list_sub_expenses_ok() -> None:
    parent = _expense(id=uuid.uuid4())
    child = _expense(id=uuid.uuid4(), actor="u-1")
    child.parent_expense_id = parent.id
    sess = fake_session(
        result((child, "VS-1")),        # children joined with Budget
        result(("u-1", "Bob", None)),   # _actor_names
        gets=[parent],
    )
    svc = BudgetTreeService(sess)
    out = await svc.list_sub_expenses(parent.id)
    assert len(out) == 1
    assert out[0].parent_expense_id == parent.id
    assert out[0].path_key == "VS-1"


async def test_list_sub_expenses_parent_missing() -> None:
    svc = BudgetTreeService(fake_session(gets=[None]))
    with pytest.raises(NotFoundError):
        await svc.list_sub_expenses(uuid.uuid4())


async def test_create_sub_booking_inherits_parent() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    parent = _expense(id=uuid.uuid4(), budget_id=node.id, kind="expense", amount="0.00")
    sess = fake_session(
        result(Decimal("12.00")),   # _recompute_parent_amount
        result(node),               # _get_node
        result(),                   # _actor_names
        gets=[parent, parent],      # _subbooking_parent_or_error and the recompute get
    )
    svc = BudgetTreeService(sess)
    out = await svc.create_sub_booking(
        parent.id, SubBookingCreate(amount=Decimal("12.00"), description="Teil"), actor="u"
    )
    assert out.parent_expense_id == parent.id
    assert out.amount == Decimal("12.00")
    assert out.description == "Teil"
    assert parent.amount == Decimal("12.00")   # the parent holds the sum of the children


async def test_create_sub_booking_on_transfer_rejected() -> None:
    parent = _expense(id=uuid.uuid4(), transfer_id=uuid.uuid4())
    svc = BudgetTreeService(fake_session(gets=[parent]))
    with pytest.raises(ValidationProblem):
        await svc.create_sub_booking(
            parent.id, SubBookingCreate(amount=Decimal("1.00"), description="x"), actor="u"
        )


async def test_create_sub_booking_nested_rejected() -> None:
    """Sub-bookings do not nest."""
    child = _expense(id=uuid.uuid4())
    child.parent_expense_id = uuid.uuid4()
    svc = BudgetTreeService(fake_session(gets=[child]))
    with pytest.raises(ValidationProblem):
        await svc.create_sub_booking(
            child.id, SubBookingCreate(amount=Decimal("1.00"), description="x"), actor="u"
        )


async def test_create_sub_booking_parent_missing() -> None:
    svc = BudgetTreeService(fake_session(gets=[None]))
    with pytest.raises(NotFoundError):
        await svc.create_sub_booking(
            uuid.uuid4(), SubBookingCreate(amount=Decimal("1.00"), description="x"), actor="u"
        )


async def test_delete_expense_child_recomputes_parent() -> None:
    parent = _expense(id=uuid.uuid4(), amount="50.00")
    child = _expense(id=uuid.uuid4(), amount="20.00")
    child.parent_expense_id = parent.id
    sess = fake_session(
        result(child),               # select the booking to delete
        result(Decimal("30.00")),    # _recompute sums the remaining children
        gets=[parent],               # the parent for _recompute
    )
    svc = BudgetTreeService(sess)
    await svc.delete_expense(child.id)
    assert child in sess.deleted
    assert parent.amount == Decimal("30.00")


async def test_delete_expense_child_parent_vanished_no_update() -> None:
    """Stay quiet when the parent booking disappears during a delete.

    The sum of the children is greater than 0, but `get` no longer loads the parent
    booking after a parallel delete. The service writes no amount and raises no error
    (#subbookings).
    """
    child = _expense(id=uuid.uuid4(), amount="20.00")
    child.parent_expense_id = uuid.uuid4()
    sess = fake_session(
        result(child),               # select the booking to delete
        result(Decimal("30.00")),    # _recompute sums the remaining children, above 0
        gets=[],                     # the parent get returns None, the parent is gone
    )
    svc = BudgetTreeService(sess)
    await svc.delete_expense(child.id)
    assert child in sess.deleted
    assert sess.committed == 1


async def test_delete_last_child_keeps_parent_amount() -> None:
    parent = _expense(id=uuid.uuid4(), amount="50.00")
    child = _expense(id=uuid.uuid4(), amount="50.00")
    child.parent_expense_id = parent.id
    sess = fake_session(
        result(child),        # select
        result(Decimal("0")),  # a sum of 0 keeps the amount
        gets=[parent],
    )
    svc = BudgetTreeService(sess)
    await svc.delete_expense(child.id)
    assert parent.amount == Decimal("50.00")   # no children left, so unchanged


async def test_update_expense_amount_readonly_on_parent() -> None:
    parent = _expense(id=uuid.uuid4(), amount="50.00")
    sess = fake_session(result((parent.id, 2)), gets=[parent])  # _child_counts finds 2
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.update_expense(parent.id, ExpenseUpdate(amount=Decimal("99.00")))


async def test_update_expense_subbooking_inherited_rejected() -> None:
    child = _expense(id=uuid.uuid4())
    child.parent_expense_id = uuid.uuid4()
    svc = BudgetTreeService(fake_session(gets=[child]))
    with pytest.raises(ValidationProblem):
        await svc.update_expense(child.id, ExpenseUpdate(budgetId=uuid.uuid4()))


async def test_update_expense_child_amount_recomputes_parent() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    parent = _expense(id=uuid.uuid4(), amount="20.00")
    child = _expense(id=uuid.uuid4(), budget_id=node.id, amount="20.00")
    child.parent_expense_id = parent.id
    sess = fake_session(
        result(),                   # _child_counts: the child has no children
        result(Decimal("35.00")),   # _recompute sums for the parent
        result(node),               # _get_node after the commit
        gets=[child, parent],       # the update get and the recompute get
    )
    svc = BudgetTreeService(sess)
    out = await svc.update_expense(child.id, ExpenseUpdate(amount=Decimal("35.00")))
    assert out.amount == Decimal("35.00")
    assert parent.amount == Decimal("35.00")


# --------------------------------------------------------------------------
# Fiscal-year delete: the 409 guard keeps money rows from being dropped.
# --------------------------------------------------------------------------


async def test_delete_fiscal_year_ok() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
    # Queue: the node, the fiscal year, then the three guard probes (all empty).
    sess = fake_session(result(top), result(fy), result(), result(), result())
    svc = BudgetTreeService(sess, actor="u")
    await svc.delete_fiscal_year(top.id, fy.id)
    assert sess.deleted == [fy]
    assert sess.committed == 1


async def test_delete_fiscal_year_not_top_level_422() -> None:
    child = _budget(id=uuid.uuid4(), parent_id=uuid.uuid4(), path_key="VS-1", key="1")
    svc = BudgetTreeService(fake_session(result(child)))
    with pytest.raises(ValidationProblem):
        await svc.delete_fiscal_year(child.id, uuid.uuid4())


async def test_delete_fiscal_year_of_other_budget_404() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    foreign = _fy(id=uuid.uuid4(), budget_id=uuid.uuid4())
    svc = BudgetTreeService(fake_session(result(top), result(foreign)))
    with pytest.raises(NotFoundError):
        await svc.delete_fiscal_year(top.id, foreign.id)


async def test_delete_fiscal_year_with_bookings_409() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
    sess = fake_session(
        result(top), result(fy), result(uuid.uuid4()), result(), result()
    )
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError) as ei:
        await svc.delete_fiscal_year(top.id, fy.id)
    assert "bookings" in str(ei.value)
    assert sess.deleted == []


async def test_delete_fiscal_year_with_allocations_409() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
    sess = fake_session(
        result(top), result(fy), result(), result(uuid.uuid4()), result()
    )
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError) as ei:
        await svc.delete_fiscal_year(top.id, fy.id)
    assert "allocations" in str(ei.value)


async def test_delete_fiscal_year_with_applications_409() -> None:
    # `application.fiscal_year_id` has no cascade, so an unguarded delete would
    # fail on the foreign key with a 500.
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
    sess = fake_session(
        result(top), result(fy), result(), result(), result(uuid.uuid4())
    )
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError) as ei:
        await svc.delete_fiscal_year(top.id, fy.id)
    assert "applications" in str(ei.value)


# --------------------------------------------------------------------------
# Transfers as a first-class entity: read, patch and delete both legs.
# --------------------------------------------------------------------------


def _transfer_pair(*, transfer_id=None, src=None, dst=None, fy=None, actor=None):  # noqa: ANN001
    tid = transfer_id or uuid.uuid4()
    out = _expense(
        budget_id=src or uuid.uuid4(), fy_id=fy or uuid.uuid4(), kind="expense",
        amount="100.00", transfer_id=tid, actor=actor,
    )
    income = _expense(
        budget_id=dst or uuid.uuid4(), fy_id=out.fiscal_year_id, kind="income",
        amount="100.00", transfer_id=tid, actor=actor,
    )
    return tid, out, income


async def test_get_transfer_joins_both_legs() -> None:
    tid, out, income = _transfer_pair(actor="u")
    sess = fake_session(
        result(out, income),  # _legs
        result((out.budget_id, "VS-1"), (income.budget_id, "VS-2")),  # _path_keys
        result(("u", "Uwe", None)),  # _actor_names
    )
    row = await BudgetTreeService(sess).get_transfer(tid)
    assert row.transfer_id == tid
    assert row.expense_id == out.id and row.income_id == income.id
    assert row.from_path_key == "VS-1" and row.to_path_key == "VS-2"
    assert row.actor_name == "Uwe"


async def test_get_transfer_missing_leg_404() -> None:
    # A single booking without its counterpart is not a transfer entity.
    _tid, out, _income = _transfer_pair()
    svc = BudgetTreeService(fake_session(result(out)))
    with pytest.raises(NotFoundError):
        await svc.get_transfer(uuid.uuid4())


async def test_get_transfer_missing_expense_leg_404() -> None:
    _tid, _out, income = _transfer_pair()
    svc = BudgetTreeService(fake_session(result(income)))
    with pytest.raises(NotFoundError):
        await svc.get_transfer(uuid.uuid4())


async def test_path_keys_empty_set_skips_query() -> None:
    svc = BudgetTreeService(fake_session())
    assert await svc._path_keys(set()) == {}


async def test_list_transfers_unfiltered() -> None:
    tid, out, income = _transfer_pair()
    sess = fake_session(
        result(1),  # count
        result(out),  # source legs
        result(income),  # income legs
        result((out.budget_id, "VS-1"), (income.budget_id, "VS-2")),  # path keys
    )
    page = await BudgetTreeService(sess).list_transfers_paged()
    assert page.total == 1 and page.limit == 50
    assert page.items[0].transfer_id == tid
    assert page.items[0].actor_name is None


async def test_list_transfers_all_filters_and_search() -> None:
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    tid, out, income = _transfer_pair(actor="u")
    sess = fake_session(
        result(node),  # _get_node for the budget filter
        result(1),  # count
        result(out),
        result(income),
        result((out.budget_id, "VS-1"), (income.budget_id, "VS-2")),
        result(("u", "Uwe", None)),
    )
    page = await BudgetTreeService(sess).list_transfers_paged(
        transfer_id=tid,
        budget_id=node.id,
        fiscal_year_id=out.fiscal_year_id,
        q="Umbuchung",
        amount_min=Decimal("1"),
        amount_max=Decimal("999"),
        created_from="2026-01-01",
        created_to="2026-12-31",
        sort="amount",
        order="asc",
        limit=10,
        offset=0,
    )
    assert page.items[0].transfer_id == tid


async def test_list_transfers_blank_q_and_nullable_date_sort() -> None:
    # A blank `q` adds no search clause, and a nullable date column sorts nulls last.
    _tid, out, income = _transfer_pair()
    sess = fake_session(
        result(1),
        result(out),
        result(income),
        result((out.budget_id, "VS-1"), (income.budget_id, "VS-2")),
    )
    page = await BudgetTreeService(sess).list_transfers_paged(
        q="   ", sort="invoiceDate", order="desc"
    )
    assert page.total == 1


async def test_list_transfers_empty_page() -> None:
    # No count row and no source leg: `total` falls back to 0 and the assembly
    # returns early without a second query.
    sess = fake_session(result(), result())
    page = await BudgetTreeService(sess).list_transfers_paged()
    assert page.total == 0 and page.items == []


async def test_list_transfers_skips_leg_without_counterpart() -> None:
    # A source leg whose income row is gone is no transfer and drops out of the page.
    _tid, out, _income = _transfer_pair()
    sess = fake_session(result(1), result(out), result())
    page = await BudgetTreeService(sess).list_transfers_paged()
    assert page.total == 1 and page.items == []


async def test_update_transfer_patches_both_legs() -> None:
    tid, out, income = _transfer_pair(actor="u")
    sess = fake_session(
        result(out, income),  # _legs
        result((out.budget_id, "VS-1"), (income.budget_id, "VS-2")),  # path keys
        result(("u", "Uwe", None)),  # actor names
    )
    row = await BudgetTreeService(sess, actor="u").update_transfer(
        tid,
        TransferUpdate(
            amount=Decimal("55.00"),
            description="Korrektur",
            note="Beleg nachgereicht",
            invoiceDate=date(2026, 6, 1),
            paymentDate=date(2026, 6, 2),
            fromBudgetId=out.budget_id,  # repeating the pair is allowed
            toBudgetId=income.budget_id,
        ),
    )
    assert row.amount == Decimal("55.00") and row.note == "Beleg nachgereicht"
    # Both legs carry the same values, so the pair never drifts apart.
    assert income.amount == Decimal("55.00")
    assert income.description == "Korrektur" and income.note == "Beleg nachgereicht"
    assert income.invoice_date == date(2026, 6, 1)
    assert income.payment_date == date(2026, 6, 2)
    assert sess.committed == 1


async def test_update_transfer_audit_entry_is_not_revertable() -> None:
    # The entry records the prior values under `prior`, NOT under `before`. A
    # one-sided revert would desync the pair, so the log must not offer it.
    from app.modules.audit.service import AuditService

    tid, out, income = _transfer_pair()
    entries: list[Any] = []
    sess = fake_session(
        result(out, income),
        result((out.budget_id, "VS-1"), (income.budget_id, "VS-2")),
    )
    original_add = sess.add

    def _capture(obj: Any) -> None:
        entries.append(obj)
        original_add(obj)

    sess.add = _capture
    await BudgetTreeService(sess, actor="u").update_transfer(
        tid, TransferUpdate(amount=Decimal("7.00"))
    )
    audit = [e for e in entries if isinstance(e, AuditEntry)]
    assert len(audit) == 1
    assert audit[0].action == AuditAction.BUDGET_EXPENSE_UPDATE
    assert audit[0].target_type == "budget_transfer"
    assert "before" not in audit[0].data
    assert audit[0].data["prior"]["amount"] == "100.00"
    flags = await AuditService(cast("Any", sess)).revertable_flags([audit[0]])
    assert flags[audit[0].id] is False


async def test_update_transfer_rejects_new_source_409() -> None:
    tid, out, income = _transfer_pair()
    sess = fake_session(result(out, income))
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess).update_transfer(
            tid, TransferUpdate(fromBudgetId=uuid.uuid4())
        )
    assert ei.value.code == "transfer_cost_centres_immutable"
    assert sess.committed == 0


async def test_update_transfer_rejects_new_target_409() -> None:
    tid, out, income = _transfer_pair()
    sess = fake_session(result(out, income))
    with pytest.raises(ConflictError):
        await BudgetTreeService(sess).update_transfer(
            tid, TransferUpdate(toBudgetId=uuid.uuid4())
        )


async def test_update_transfer_unknown_404() -> None:
    svc = BudgetTreeService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc.update_transfer(uuid.uuid4(), TransferUpdate(amount=Decimal("1")))


async def test_delete_transfer_removes_both_legs() -> None:
    tid, out, income = _transfer_pair(actor="u")
    sess = fake_session(result(out, income))
    await BudgetTreeService(sess, actor="u").delete_transfer(tid)
    assert sess.deleted == [out, income]
    assert sess.committed == 1


async def test_delete_transfer_unknown_404() -> None:
    svc = BudgetTreeService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc.delete_transfer(uuid.uuid4())
