"""Full branch and line coverage for `app.modules.budget.tree`.

The module is critical (`budget` needs 100 % branch coverage).
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
from tests._support.identity_rows import sub_ref


class _R:
    """Minimal `Result` stub: FIFO items, iterable, `scalars()`/`all()`/`one()`/`first()`."""

    def __init__(self, *items: Any) -> None:
        self._items = list(items)

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None

    def scalars(self) -> _R:
        return self

    def all(self) -> list[Any]:
        return list(self._items)

    def one(self) -> Any:
        return self._items[0]

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
        """Queue the results and the gets that the fake session serves.

        ``bind`` is None, so ``dialect_of`` reports ``postgresql`` and the search path
        runs.
        """
        self._results = list(results)
        self._gets = list(gets)
        self.bind = None
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.flushed = 0
        self.committed = 0

    @staticmethod
    def _is_audit_stmt(stmt: Any) -> bool:
        """Report whether a statement belongs to the audit trail.

        ``audit_record`` fires two ``execute`` calls per mutation: the advisory lock and
        the ``prev_hash`` select on ``audit_entry``. The stub skips both, so the test
        queue mirrors only the domain queries of the service.
        """
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
        """Set the DB server defaults on a new object.

        The fake session has no refresh, so it sets the id (``gen_random_uuid``),
        ``created_at`` (now) and the currency (the EUR check) itself.
        """
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


def counts(all_: int = 0, inbox: int = 0, booked: int = 0, paid: int = 0) -> _R:
    """The row of the segment counts of the invoice list, the first query."""
    return _R((all_, inbox, booked, paid))


def fake_session(*results: _R, gets: list[Any] | None = None) -> Any:
    return _Session(list(results), list(gets or []))


def _budget(
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


def _fy(*, id=None, budget_id=None, year=2026, active=True):
    f = FiscalYear(
        budget_id=budget_id, year=year,
        start_date=date(year, 1, 1), end_date=date(year, 12, 31), active=active,
    )
    f.id = id or uuid.uuid4()
    return f


def _alloc(*, budget_id, fy_id, allocated):
    a = BudgetAllocation(budget_id=budget_id, fiscal_year_id=fy_id, allocated=Decimal(allocated))
    a.id = uuid.uuid4()
    return a


def _app(*, id=None, budget_id=None, fiscal_year_id=None, amount=None, data=None):
    a = Application(
        type_id=uuid.uuid4(), form_version_id=uuid.uuid4(), flow_version_id=uuid.uuid4(),
        budget_id=budget_id, fiscal_year_id=fiscal_year_id, amount=amount,
        data=data if data is not None else {},
    )
    a.id = id or uuid.uuid4()
    return a


def _expense(
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


def _invoice(*, id=None, number="R-1", gross="119.00", file_key=None,
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
    """Numeric segments sort as (0, int), other segments as (1, str): VSM-9 < VSM-10."""
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
    """A top-level key change rewrites path_key and every descendant without a parent lookup.

    The fake session serves the node, an empty sibling check, then the descendants.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    child = _budget(id=uuid.uuid4(), parent_id=node.id, path_key="VS-800", key="800")
    sess = fake_session(result(node), result(), result(child))
    svc = BudgetTreeService(sess)
    out = await svc.update_node(node.id, _node_update(key="VV"))
    assert out.key == "VV" and out.path_key == "VV"
    assert child.path_key == "VV-800"


def _node_update(**kw: Any) -> BudgetNodeUpdate:
    return BudgetNodeUpdate(**kw)


async def test_update_node_rename_key_child_with_parent_lookup() -> None:
    """A child key change looks up the parent path.

    The fake session serves the node, an empty sibling check, the parent, then no
    descendants.
    """
    parent = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), parent_id=parent.id, path_key="VS-800", key="800")
    sess = fake_session(result(node), result(), result(parent), result())
    svc = BudgetTreeService(sess)
    out = await svc.update_node(node.id, _node_update(key="900"))
    assert out.key == "900" and out.path_key == "VS-900"


async def test_update_node_rename_key_invalid() -> None:
    """A bad key raises before the sibling check, so one result is enough."""
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    sess = fake_session(result(node))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.update_node(node.id, _node_update(key="bad-key"))


async def test_update_node_rename_key_conflict() -> None:
    """A sibling with the new key gives a conflict."""
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    other = _budget(id=uuid.uuid4(), path_key="VV", key="VV")
    sess = fake_session(result(node), result(other))
    svc = BudgetTreeService(sess)
    from app.shared.errors import ConflictError

    with pytest.raises(ConflictError):
        await svc.update_node(node.id, _node_update(key="VV"))


async def test_update_node_rename_key_same_value_noop() -> None:
    """An unchanged key does not run ``_rename_key``."""
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    sess = fake_session(result(node))
    svc = BudgetTreeService(sess)
    out = await svc.update_node(node.id, _node_update(key="VS", name="Neu"))
    assert out.key == "VS" and out.name == "Neu"


async def test_update_node_stichtag_changed_but_not_top_level() -> None:
    """A changed fiscal start date on a child skips the fiscal-year rederive.

    The fake session serves the node only, so ``_fiscal_years_of`` is never called.
    """
    parent_id = uuid.uuid4()
    node = _budget(id=uuid.uuid4(), parent_id=parent_id, path_key="VS-800", key="800",
                   fiscal_start_month=1)
    sess = fake_session(result(node))
    svc = BudgetTreeService(sess)
    out = await svc.update_node(node.id, _node_update(fiscalStartMonth=7))
    assert out.fiscal_start_month == 7


async def test_create_fiscal_year_impossible_stichtag_raises_422() -> None:
    """An impossible fiscal start date (February 31) gives 422, not 500.

    Legacy rows and direct calls can carry such a date. The service wraps the ValueError
    of ``fiscal_year_bounds``. Only ``_require_top_level`` reads the session, because
    the error comes before the duplicate check.
    """
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS",
                  fiscal_start_month=2, fiscal_start_day=31)
    sess = fake_session(result(top))
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
    """A view_gremium_id on an ancestor path prefix opens the node.

    The rows hold view_gremium_id per path prefix: VS carries g, the other prefixes are
    None.
    """
    g = uuid.uuid4()
    node = _budget(id=uuid.uuid4(), path_key="VS-800-04", key="04")
    sess = fake_session(result(node), result(g, None, None))
    svc = BudgetTreeService(sess)
    assert await svc.can_view_node(node.id, {g}) is True


async def test_can_view_node_no_match() -> None:
    """No view_gremium_id on any path prefix hides the node."""
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    sess = fake_session(result(node), result(None))
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
    """The fiscal-year filter lists the rows of the node.

    The fake session serves the node, then the rows.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    fy_id = uuid.uuid4()
    app = _app(budget_id=node.id, fiscal_year_id=fy_id, amount=Decimal("100"),
               data={"title": "Antrag X"})
    app.current_state_id = uuid.uuid4()
    app.currency = "EUR"
    app.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    row = (app, "VS", {"de": "In Prüfung"}, "#abc")
    sess = fake_session(result(node), result(row))
    svc = BudgetTreeService(sess)
    out = await svc.list_applications(node.id, fiscal_year_id=fy_id)
    assert len(out) == 1
    assert out[0].title == "Antrag X"
    assert out[0].state_label == {"de": "In Prüfung"}


async def test_list_applications_no_filter_empty_state_label() -> None:
    """A falsy state_label ("" or None) maps to None."""
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    app = _app(budget_id=node.id, fiscal_year_id=uuid.uuid4(), amount=Decimal("50"))
    app.current_state_id = None
    app.currency = "EUR"
    app.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    row = (app, "VS", None, None)
    sess = fake_session(result(node), result(row))
    svc = BudgetTreeService(sess)
    out = await svc.list_applications(node.id)
    assert out[0].state_label is None


async def test_book_expense_standalone_with_actor() -> None:
    """A standalone booking resolves the display name of its actor.

    The fake session serves ``_get_node`` for the budget id, ``_top_level``,
    ``_fiscal_years_of`` and ``_actor_names``, which selects tuples of sub, display_name
    and email.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    sess = fake_session(
        result(node),
        result(top),
        result(fy),
        result(sub_ref("u-1", "Alice", "a@x")),
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(amount=Decimal("42.00"), description="Rechnung", budgetId=node.id)
    out = await svc.book_expense(payload, actor="u-1")
    assert out.amount == Decimal("42.00")
    assert out.actor_name == "Alice"


async def test_book_expense_commit_false_defers_commit() -> None:
    """With commit=False (bank reconciliation) the service books but the caller commits."""
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
    assert sess.committed == 0


async def test_create_expense_compat_wraps_budget_id() -> None:
    """The compat wrapper books on the given budget id.

    The actor is set, but ``_actor_names`` finds no principal row, so actor_name stays
    None.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    sess = fake_session(
        result(node), result(top), result(fy), result(),
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(amount=Decimal("5.00"), description="d", fiscalYearId=fy.id)
    out = await svc.create_expense(node.id, payload, actor="anon")
    assert out.budget_id == node.id
    assert out.actor == "anon"
    assert out.actor_name is None


async def test_book_expense_linked_to_application() -> None:
    """A booking linked to an application takes the node of the application.

    The fake session serves the application from ``session.get``, then ``_get_node`` for
    its budget id, then ``_actor_names`` without an actor row.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    fy_id = uuid.uuid4()
    app = _app(budget_id=node.id, fiscal_year_id=fy_id, data={"title": "Linked"})
    sess = fake_session(
        result(node),
        result(),
        gets=[app],
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(
        amount=Decimal("10.00"), description="d", applicationId=app.id,
    )
    out = await svc.book_expense(payload, actor="")
    assert out.application_title == "Linked"
    assert out.fiscal_year_id == fy_id


async def test_book_expense_linked_application_not_found() -> None:
    """An unknown linked application gives 404."""
    sess = fake_session(gets=[None])
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(amount=Decimal("1.00"), description="d",
                            applicationId=uuid.uuid4())
    with pytest.raises(NotFoundError):
        await svc.book_expense(payload, actor="a")


async def test_book_expense_keeps_open_invoice_open() -> None:
    """A booking does not pay its open invoice: it is "Verbucht", not paid.

    ``_require_invoice`` loads the invoice through ``session.get``.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    inv = _invoice(id=uuid.uuid4())
    sess = fake_session(
        result(node), result(top), result(fy), result(),
        gets=[inv],
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseCreate(
        amount=Decimal("10.00"), description="d", budgetId=node.id, invoiceId=inv.id,
    )
    out = await svc.book_expense(payload, actor="")
    assert out.amount == Decimal("10.00")
    assert inv.status == "open"


async def test_book_expense_paid_invoice_stays_paid() -> None:
    """A booking changes no status of an invoice that is already paid."""
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    inv = _invoice(id=uuid.uuid4())
    inv.status = "paid"
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
    """An unknown invoice gives 404."""
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top = node
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    sess = fake_session(
        result(node), result(top), result(fy),
        gets=[None],
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
    """An update writes every field and links the invoice without paying it.

    The gets are the booking, its fiscal year (missing, so open), the invoice for the
    existence check, and after the commit the application for display. The fake session
    serves ``_child_counts`` (no children), ``_get_node`` after the commit and
    ``_actor_names``. A display_name of None falls back to the email.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    app = _app(budget_id=node.id, data={"title": "T"})
    inv = _invoice(id=uuid.uuid4())
    expense = _expense(budget_id=node.id, application_id=app.id, actor="u-1")
    sess = fake_session(
        result(),
        result(node),
        result(sub_ref("u-1", None, "bob@x")),
        gets=[expense, None, inv, app],
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
    assert out.actor_name == "bob@x"
    assert inv.status == "open"
    assert expense.invoice_id == inv.id


async def test_update_expense_no_app() -> None:
    """An update of a booking without an application.

    The fake session serves ``_get_node`` after the commit and ``_actor_names`` without
    an actor.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    expense = _expense(budget_id=node.id, application_id=None, actor=None)
    sess = fake_session(
        result(node),
        result(),
        gets=[expense],
    )
    svc = BudgetTreeService(sess)
    payload = ExpenseUpdate(note=None)
    out = await svc.update_expense(expense.id, payload)
    assert out.application_title is None


async def test_update_expense_amount_none_skipped() -> None:
    """A present amount of None keeps the stored amount.

    The description is set, so the model passes ``_at_least_one``, and the amount stays
    7.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    expense = _expense(budget_id=node.id, amount="7.00")
    sess = fake_session(result(node), result(), gets=[expense])
    svc = BudgetTreeService(sess)
    payload = ExpenseUpdate(description="d2")
    out = await svc.update_expense(expense.id, payload)
    assert out.amount == Decimal("7.00")
    assert out.description == "d2"


async def test_update_expense_rebooks_within_same_top_level() -> None:
    """A booking moves to another cost center of the same top-level budget.

    ``budget_id`` and the currency follow the new node. The fiscal year of the top node
    stays fixed, so ``_resolve_fiscal_year`` passes. The fake session serves
    ``_get_node`` for the new budget, ``_top_level`` and the fiscal year for
    ``_resolve_fiscal_year``, ``_get_node`` after the commit, and ``_actor_names``
    without an actor.
    """
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    new = _budget(id=uuid.uuid4(), parent_id=top.id, path_key="VS-2", key="2", currency="CHF")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
    expense = _expense(
        budget_id=uuid.uuid4(), fy_id=fy.id, application_id=None, actor=None,
    )
    sess = fake_session(
        result(new),
        result(top),
        result(fy),
        result(new),
        result(),
        gets=[expense],
    )
    svc = BudgetTreeService(sess)
    out = await svc.update_expense(expense.id, ExpenseUpdate(budgetId=new.id))
    assert out.budget_id == new.id
    assert out.path_key == "VS-2"
    assert expense.currency == "CHF"
    assert expense.fiscal_year_id == fy.id


async def test_update_expense_rebook_across_top_level_rejected() -> None:
    """A move into a foreign top-level cost center gives 422 and writes nothing.

    The move would orphan the fiscal year that the booking keeps, which leaves a phantom
    row. ``_resolve_fiscal_year`` rejects before it writes budget_id or the currency,
    and before any commit: the fiscal year belongs to another top node.
    """
    other_top = _budget(id=uuid.uuid4(), path_key="VV", key="VV")
    new = _budget(id=uuid.uuid4(), parent_id=other_top.id, path_key="VV-2", key="2")
    fy = _fy(id=uuid.uuid4(), budget_id=uuid.uuid4())
    expense = _expense(
        budget_id=uuid.uuid4(), fy_id=fy.id, application_id=None, currency="EUR",
    )
    sess = fake_session(
        result(new),
        result(other_top),
        result(fy),
        gets=[expense],
    )
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.update_expense(expense.id, ExpenseUpdate(budgetId=new.id))
    assert expense.budget_id != new.id
    assert expense.currency == "EUR"
    assert sess.committed == 0


async def test_update_expense_rebook_unknown_budget_404() -> None:
    """An unknown target cost center gives 404, so the commit cannot fail on the foreign key."""
    expense = _expense(budget_id=uuid.uuid4(), application_id=None)
    sess = fake_session(result(), gets=[expense])
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.update_expense(expense.id, ExpenseUpdate(budgetId=uuid.uuid4()))


async def test_update_expense_clears_invoice_link_no_mark() -> None:
    """A present invoice_id of None clears the link without an invoice lookup or status flip."""
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    expense = _expense(budget_id=node.id, invoice_id=uuid.uuid4())
    sess = fake_session(result(node), result(), gets=[expense])
    svc = BudgetTreeService(sess)
    payload = ExpenseUpdate(invoiceId=None)
    out = await svc.update_expense(expense.id, payload)
    assert out.invoice_id is None


async def test_update_expense_app_missing_after_commit() -> None:
    """An application that is gone after the commit gives no application title."""
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    expense = _expense(budget_id=node.id, application_id=uuid.uuid4())
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
    """The compat list delegates to ``list_expenses_paged``.

    The fake session serves the node, the count, the rows, then ``_actor_names``.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    e = _expense(budget_id=node.id, actor="u-1")
    sess = fake_session(
        result(node),
        result(3),
        result((e, "VS", {"title": "AppT"}, "INV-1")),
        result(sub_ref("u-1", "Carol", None)),
    )
    svc = BudgetTreeService(sess)
    out = await svc.list_expenses(node.id)
    assert len(out) == 1
    assert out[0].application_title == "AppT"
    assert out[0].invoice_number == "INV-1"
    assert out[0].actor_name == "Carol"


async def test_list_expenses_paged_no_filters_empty() -> None:
    """Without a budget id ``_get_node`` is skipped, and a total of None becomes 0."""
    sess = fake_session(result(None), result())
    svc = BudgetTreeService(sess)
    page = await svc.list_expenses_paged()
    assert page.total == 0
    assert page.items == []


async def test_list_expenses_paged_all_filters_and_search() -> None:
    """Every filter and the search apply in one query.

    The fake session serves the node, the count and the rows. A row with data None has
    no title. ``_actor_names`` gets an empty set and returns {}.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    e = _expense(budget_id=node.id, actor=None)
    sess = _pg_session(
        result(node),
        result(1),
        result((e, "VS", None, None)),
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
    """An expense_id filters to the exact booking of a deep link.

    A budget_id of None skips ``_get_node``.
    """
    e = _expense(actor=None)
    sess = fake_session(result(1), result((e, "VS", None, None)))
    svc = BudgetTreeService(sess)
    page = await svc.list_expenses_paged(expense_id=e.id)
    assert page.total == 1
    assert page.items[0].id == e.id


async def test_list_expenses_paged_blank_query_no_rank() -> None:
    """A whitespace-only q skips the trigram rank. The sort is by amount, descending."""
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
    """A sort by paymentDate puts nulls last. An order of None defaults to desc."""
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
    """A transfer leg deletes both legs: the booking, then the pair."""
    tid = uuid.uuid4()
    e = _expense(transfer_id=tid)
    pair_a = _expense(transfer_id=tid, kind="expense")
    pair_b = _expense(transfer_id=tid, kind="income")
    sess = fake_session(result(e), result(pair_a, pair_b))
    svc = BudgetTreeService(sess)
    await svc.delete_expense(e.id)
    assert sess.deleted == [pair_a, pair_b]


async def test_list_invoices_paged_all_filters_and_search() -> None:
    """Every filter and the search apply. The session serves the counts, the count and the rows."""
    inv = _invoice()
    sess = _pg_session(counts(2, 2), result(2), result(inv))
    svc = BudgetTreeService(sess)
    page = await svc.list_invoices_paged(
        q="acme", status="open", gross_min=Decimal("1"), gross_max=Decimal("999"),
        issue_from="2026-01-01", issue_to="2026-12-31",
        due_from="2026-01-01", due_to="2026-12-31", limit=20, offset=0,
    )
    assert page.total == 2
    assert page.items[0].has_file is False


@pytest.mark.parametrize("booked", [True, False])
async def test_list_invoices_paged_by_segment(booked: bool) -> None:
    """``booked`` narrows to invoices with or without a visible booking.

    The session serves the counts, the count and the rows.
    """
    inv = _invoice()
    sess = _pg_session(counts(1, 0, 1), result(1), result(inv))
    page = await BudgetTreeService(sess).list_invoices_paged(status="open", booked=booked)
    assert page.total == 1
    assert page.counts.booked == 1


async def test_list_invoices_paged_by_exact_id() -> None:
    """``id`` narrows the list to one invoice, which is where a search hit lands.

    The session serves the counts, the count and the rows.
    """
    inv = _invoice()
    sess = _pg_session(counts(1, 1), result(1), result(inv))
    svc = BudgetTreeService(sess)
    page = await svc.list_invoices_paged(invoice_id=inv.id)
    assert page.total == 1
    assert page.items[0].id == inv.id


async def test_list_invoices_paged_no_search_blank_q() -> None:
    """A count of None becomes 0, with no rows."""
    sess = fake_session(counts(), result(None), result())
    svc = BudgetTreeService(sess)
    page = await svc.list_invoices_paged(q="")
    assert page.total == 0
    assert page.counts.model_dump() == {"all": 0, "inbox": 0, "booked": 0, "paid": 0}


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
    """An invoice without a file commits once.

    ``create_invoice`` flushes for the id, and ``audit_record`` flushes too.
    """
    sess = fake_session()
    svc = BudgetTreeService(sess)
    out = await svc.create_invoice(
        InvoiceCreate(number="R-2", grossAmount=Decimal("50.00")), actor="u"
    )
    assert out.number == "R-2"
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


async def test_create_invoice_cleans_the_client_file_name() -> None:
    svc = BudgetTreeService(fake_session())
    out = await svc.create_invoice(
        InvoiceCreate(
            number="R-4", grossAmount=Decimal("10.00"),
            fileToken="invoices/x/a.pdf", fileName="../Beleg\u202e März €\r\n.pdf",
            fileMime="application/pdf",
        ),
        actor="u",
    )
    assert out.file_name == "Beleg März €.pdf"
    no_name = await BudgetTreeService(fake_session()).create_invoice(
        InvoiceCreate(number="R-5", grossAmount=Decimal("1"), fileToken="invoices/x/b.pdf"),
        actor="u",
    )
    assert no_name.file_name == "beleg.pdf"


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
    """Fields that the payload does not set keep their values.

    Only ``note`` is set, so the gross, status and supplier fields are not written.
    """
    inv = _invoice(gross="119.00")
    sess = fake_session(gets=[inv])
    svc = BudgetTreeService(sess)
    out = await svc.update_invoice(inv.id, InvoiceUpdate(note="nur Notiz"))
    assert out.note == "nur Notiz"
    assert out.gross_amount == Decimal("119.00")


async def test_update_invoice_gross_and_status_explicit_none() -> None:
    """An explicit None for gross_amount and status keeps both values."""
    inv = _invoice(gross="119.00")
    sess = fake_session(gets=[inv])
    svc = BudgetTreeService(sess)
    out = await svc.update_invoice(
        inv.id, InvoiceUpdate(supplier="S", grossAmount=None, status=None)
    )
    assert out.supplier == "S"
    assert out.gross_amount == Decimal("119.00")
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
    """A storage error on the remove is logged, not raised, and the delete commits."""
    inv = _invoice(file_key="invoices/x/a.pdf")
    sess = fake_session(gets=[inv])

    class _Storage:
        async def put(self, *a: Any) -> None: ...
        async def get(self, k: str) -> bytes:
            return b""
        async def remove(self, key: str) -> None:
            raise StorageError("gone")

    svc = BudgetTreeService(sess, storage=cast("Any", _Storage()))
    await svc.delete_invoice(inv.id)
    assert sess.committed == 1


async def test_delete_invoice_with_file_but_no_storage() -> None:
    """Without storage the delete makes no remove attempt."""
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
    """A found invoice id means the number exists."""
    sess = fake_session(result(uuid.uuid4()))
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
    monkeypatch.setattr(invoices_mod, "sanitize_display_name", lambda fn: "safe.pdf")
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    res = await svc.store_invoice_file(b"%PDF-1.4", filename="beleg.pdf")
    assert res.file_name == "safe.pdf"
    assert res.file_mime == "application/pdf"
    assert res.file_token.startswith("invoices/")


async def test_store_invoice_file_keeps_the_unicode_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The display name keeps its Unicode, and the object key stays ASCII."""
    monkeypatch.setattr(invoices_mod, "validate_upload", lambda fn, data: "application/pdf")
    svc = BudgetTreeService(fake_session(), storage=_ok_storage(), settings=_settings())
    res = await svc.store_invoice_file(b"%PDF-1.4", filename="../Rechnung Müller €.pdf")
    assert res.file_name == "Rechnung Müller €.pdf"
    assert res.file_token.startswith("invoices/")
    assert res.file_token.endswith("/Rechnung Muller _.pdf")
    assert res.file_token.isascii()


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
    """A parsed invoice without a stored number is no duplicate."""
    monkeypatch.setattr(invoices_mod, "validate_upload", lambda fn, data: "application/pdf")
    monkeypatch.setattr(invoices_mod, "sanitize_display_name", lambda fn: "safe.pdf")
    parsed = ParsedInvoice(
        number="R-100", issue_date=date(2026, 1, 1), due_date=date(2026, 2, 1),
        supplier="ACME", net_amount=Decimal("100"), tax_amount=Decimal("19"),
        gross_amount=Decimal("119"), currency="EUR",
    )
    monkeypatch.setattr(invoices_mod, "parse_zugferd_pdf", lambda data: parsed)
    sess = fake_session(result())
    svc = BudgetTreeService(sess, storage=_ok_storage(), settings=_settings())
    res = await svc.parse_invoice_file(b"%PDF-1.4", filename="r.pdf")
    assert res.number == "R-100"
    assert res.gross_amount == Decimal("119")
    assert res.file_token.startswith("invoices/")
    assert res.duplicate is False


async def test_parse_invoice_file_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A parsed invoice whose number exists is a duplicate."""
    monkeypatch.setattr(invoices_mod, "validate_upload", lambda fn, data: "application/pdf")
    monkeypatch.setattr(invoices_mod, "sanitize_display_name", lambda fn: "safe.pdf")
    parsed = ParsedInvoice(
        number="DUP", issue_date=None, due_date=None, supplier=None,
        net_amount=None, tax_amount=None, gross_amount=Decimal("5"), currency="EUR",
    )
    monkeypatch.setattr(invoices_mod, "parse_zugferd_pdf", lambda data: parsed)
    sess = fake_session(result(uuid.uuid4()))
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
    """A transfer books both legs.

    The fake session serves the source node, the destination node, then ``_top_level``
    and ``_get_fiscal_year`` for each side.
    """
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    src = _budget(id=uuid.uuid4(), parent_id=top.id, path_key="VS-1", key="1", currency="EUR")
    dst = _budget(id=uuid.uuid4(), parent_id=top.id, path_key="VS-2", key="2", currency="EUR")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
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
    """Two different fiscal years on the legs give 422.

    The payload names fy1, but the resolver reads the queue: the source resolves to fy1
    and the destination to fy2. Both pass the top-level check, so only the mismatch
    guard can reject.
    """
    top1 = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top2 = _budget(id=uuid.uuid4(), path_key="VV", key="VV")
    src = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    dst = _budget(id=uuid.uuid4(), path_key="VV", key="VV")
    fy1 = _fy(id=uuid.uuid4(), budget_id=top1.id)
    fy2 = _fy(id=uuid.uuid4(), budget_id=top2.id)
    sess = fake_session(
        result(src), result(dst),
        result(top1), result(fy1),
        result(top2), result(fy2),
    )
    svc = BudgetTreeService(sess)
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
    sess = fake_session(result(sub_ref(p1.sub, p1.display_name, p1.email),
                               sub_ref(p2.sub, p2.display_name, p2.email)))
    svc = BudgetTreeService(sess)
    out = await svc._actor_names({"a", "b", ""})
    assert out == {"a": "Anna", "b": "b@x"}


async def test_actor_names_fallback_to_sub() -> None:
    """A display_name of None and an email of None fall back to the sub."""
    sess = fake_session(result(sub_ref("c", None, None)))
    svc = BudgetTreeService(sess)
    out = await svc._actor_names({"c"})
    assert out == {"c": "c"}


async def test_actor_names_follow_a_merge() -> None:
    """A merged account shows the name of the account it was merged into."""
    target = uuid.uuid4()
    sess = fake_session(result(sub_ref("old", "Alt", None, merged=(target, "Neu", None))))
    svc = BudgetTreeService(sess)
    assert await svc._actor_names({"old"}) == {"old": "Neu"}


async def test_get_tree_accepted_remaining_nonpositive_skipped() -> None:
    """Skip the bound row when an accepted application is spent in full.

    Expenses greater than or equal to the amount leave remaining <= 0 (branch
    1590->1582).

    The expense spends the application in full, so the remaining 0 binds nothing.
    """
    fy_id = uuid.uuid4()
    app_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS", accepted=["approved"])
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    app_row = (app_id, "VS", fy_id, Decimal("100"), Decimal("100"), "approved")
    exp_row = ("VS", fy_id, Decimal("100"), "expense", app_id)
    sess = fake_session(result(top), result(alloc), result(app_row), result(exp_row))
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.bound == Decimal("0")
    assert view.expended == Decimal("100")


async def test_get_tree_requested_remaining_nonpositive_skipped() -> None:
    """Skip the requested row when an in-flight application is spent in full.

    Expenses greater than or equal to the amount leave remaining <= 0 (branch
    1599->1582).

    The top budget has no accepted or denied keys, so the submitted application is in
    flight.
    """
    fy_id = uuid.uuid4()
    app_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="500")
    app_row = (app_id, "VS", fy_id, Decimal("80"), Decimal("80"), "submitted")
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
    app_row = (uuid.uuid4(), "VS", fy_id, Decimal("999"), Decimal("999"), "rejected")
    sess = fake_session(result(top), result(alloc), result(app_row), result())
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.bound == Decimal("0")
    assert view.requested == Decimal("0")


async def test_get_tree_with_gremium_scope() -> None:
    """Reach scope_forest with visible_gremium_ids set."""
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
    """With an actor set, ``_audit`` calls ``audit_record`` with that sub.

    The fake session serves the node, no child and no allocation.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    sess = fake_session(result(node), result(), result())
    svc = BudgetTreeService(sess, actor="admin-sub")
    await svc.delete_node(node.id)
    assert sess.committed == 1


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


async def test_revert_expense_create_keeps_paid_invoice_paid() -> None:
    """A user marked the invoice paid. The revert of a booking does not undo that.

    The revert does not load the invoice.
    """
    inv = _invoice()
    inv.status = "paid"
    exp = _expense(id=uuid.uuid4(), invoice_id=inv.id)
    sess = fake_session(gets=[exp])
    svc = BudgetTreeService(sess, actor="admin")
    await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_CREATE, exp.id), "admin")
    assert inv.status == "paid"
    assert exp in sess.deleted and sess.committed == 1


async def test_revert_transfer_create_deletes_both_rows() -> None:
    """The revert of a transfer create deletes both rows of the transfer id."""
    tid = uuid.uuid4()
    r1 = _expense(transfer_id=tid)
    r2 = _expense(transfer_id=tid)
    sess = fake_session(result(r1, r2))
    svc = BudgetTreeService(sess, actor="admin")
    await svc.revert_audit(_entry(AuditAction.BUDGET_TRANSFER_CREATE, tid), "admin")
    assert r1 in sess.deleted and r2 in sess.deleted and sess.committed == 1


async def test_revert_transfer_create_already_reverted() -> None:
    """A transfer without rows left is already reverted."""
    sess = fake_session(result())
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
    svc.delete_node = stub
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
    """The revert of a node update restores the prior values. The node is not stale."""
    node = _budget(id=uuid.uuid4(), name="Neu")
    svc = BudgetTreeService(fake_session(gets=[node]), actor="admin")
    stub = _AsyncStub()
    svc.update_node = stub  # type: ignore[method-assign]
    data = {"before": {"name": "Alt"}, "after": {"name": "Neu"}}
    await svc.revert_audit(_entry(AuditAction.BUDGET_NODE_UPDATE, node.id, data), "admin")
    assert stub.calls and stub.calls[0][0][1].name == "Alt"


async def test_revert_node_update_no_after_is_best_effort() -> None:
    """Without ``after`` the revert runs no stale check."""
    node = _budget(id=uuid.uuid4(), name="X")
    svc = BudgetTreeService(fake_session(gets=[node]), actor="admin")
    stub = _AsyncStub()
    svc.update_node = stub  # type: ignore[method-assign]
    data = {"before": {"name": "Alt"}}
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
    """A missing allocation row makes the revert stale."""
    bid, fy = uuid.uuid4(), uuid.uuid4()
    svc = BudgetTreeService(fake_session(result()), actor="admin")
    data = {"fiscalYearId": str(fy), "allocated": "100"}
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_ALLOCATION_SET, bid, data), "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_allocation_stale_when_set_value_absent() -> None:
    """An entry without ``allocated`` has no set value, so the revert is stale."""
    bid, fy = uuid.uuid4(), uuid.uuid4()
    alloc = _alloc(budget_id=bid, fy_id=fy, allocated="100")
    svc = BudgetTreeService(fake_session(result(alloc)), actor="admin")
    data = {"fiscalYearId": str(fy)}
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_ALLOCATION_SET, bid, data), "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_allocation_stale_when_value_changed() -> None:
    """A current value of 200 against the set value of 100 makes the revert stale."""
    bid, fy = uuid.uuid4(), uuid.uuid4()
    alloc = _alloc(budget_id=bid, fy_id=fy, allocated="200")
    svc = BudgetTreeService(fake_session(result(alloc)), actor="admin")
    data = {"fiscalYearId": str(fy), "allocated": "100"}
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
    """A current amount of 90 against the recorded 70 makes the revert stale."""
    exp = _expense(id=uuid.uuid4(), amount="90.00")
    svc = BudgetTreeService(fake_session(gets=[exp]), actor="admin")
    data = {"before": {"amount": "50"}, "after": {"amount": "70"}}
    with pytest.raises(ConflictError) as ei:
        await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_UPDATE, exp.id, data), "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_expense_update_restores_decimal_tolerant() -> None:
    """The recorded "70" equals the current "70.00" (DB scale) in value, so it is not stale."""
    exp = _expense(id=uuid.uuid4(), amount="70.00")
    svc = BudgetTreeService(fake_session(gets=[exp]), actor="admin")
    stub = _AsyncStub()
    svc.update_expense = stub  # type: ignore[method-assign]
    data = {"before": {"amount": "50"}, "after": {"amount": "70"}}
    await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_UPDATE, exp.id, data), "admin")
    assert stub.calls and stub.calls[0][0][1].amount == Decimal("50")


async def test_revert_expense_update_no_after_is_best_effort() -> None:
    """Without ``after`` the revert runs no stale check."""
    exp = _expense(id=uuid.uuid4(), amount="50")
    svc = BudgetTreeService(fake_session(gets=[exp]), actor="admin")
    stub = _AsyncStub()
    svc.update_expense = stub  # type: ignore[method-assign]
    data = {"before": {"amount": "50"}}
    await svc.revert_audit(_entry(AuditAction.BUDGET_EXPENSE_UPDATE, exp.id, data), "admin")
    assert stub.calls


async def test_list_sub_expenses_ok() -> None:
    """The sub-bookings come joined with their budget, with the actor names."""
    parent = _expense(id=uuid.uuid4())
    child = _expense(id=uuid.uuid4(), actor="u-1")
    child.parent_expense_id = parent.id
    sess = fake_session(
        result((child, "VS-1")),
        result(sub_ref("u-1", "Bob", None)),
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
    """A sub-booking inherits from its parent, and the parent holds the sum of the children.

    The gets are the parent check, the fiscal year (open) and the parent for the
    recompute. The fake session serves the recomputed sum, ``_get_node`` and
    ``_actor_names``.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    parent = _expense(id=uuid.uuid4(), budget_id=node.id, kind="expense", amount="0.00")
    sess = fake_session(
        result(Decimal("12.00")),
        result(node),
        result(),
        gets=[parent, None, parent],
    )
    svc = BudgetTreeService(sess)
    out = await svc.create_sub_booking(
        parent.id, SubBookingCreate(amount=Decimal("12.00"), description="Teil"), actor="u"
    )
    assert out.parent_expense_id == parent.id
    assert out.amount == Decimal("12.00")
    assert out.description == "Teil"
    assert parent.amount == Decimal("12.00")


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
    """The delete of a child recomputes the parent from the remaining children.

    The gets are the fiscal year (open) and the parent for the recompute.
    """
    parent = _expense(id=uuid.uuid4(), amount="50.00")
    child = _expense(id=uuid.uuid4(), amount="20.00")
    child.parent_expense_id = parent.id
    sess = fake_session(
        result(child),
        result(Decimal("30.00")),
        gets=[None, parent],
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

    The remaining children sum above 0, but the parent get returns None.
    """
    child = _expense(id=uuid.uuid4(), amount="20.00")
    child.parent_expense_id = uuid.uuid4()
    sess = fake_session(
        result(child),
        result(Decimal("30.00")),
        gets=[],
    )
    svc = BudgetTreeService(sess)
    await svc.delete_expense(child.id)
    assert child in sess.deleted
    assert sess.committed == 1


async def test_delete_last_child_keeps_parent_amount() -> None:
    """The delete of the last child keeps the parent amount, because a sum of 0 changes nothing."""
    parent = _expense(id=uuid.uuid4(), amount="50.00")
    child = _expense(id=uuid.uuid4(), amount="50.00")
    child.parent_expense_id = parent.id
    sess = fake_session(
        result(child),
        result(Decimal("0")),
        gets=[None, parent],
    )
    svc = BudgetTreeService(sess)
    await svc.delete_expense(child.id)
    assert parent.amount == Decimal("50.00")


async def test_update_expense_amount_readonly_on_parent() -> None:
    """The amount of a parent with children is read-only. ``_child_counts`` finds 2."""
    parent = _expense(id=uuid.uuid4(), amount="50.00")
    sess = fake_session(result((parent.id, 2)), gets=[parent])
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
    """A new child amount recomputes the parent.

    The child has no children of its own. The gets are the child, its fiscal year (open)
    and the parent for the recompute.
    """
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    parent = _expense(id=uuid.uuid4(), amount="20.00")
    child = _expense(id=uuid.uuid4(), budget_id=node.id, amount="20.00")
    child.parent_expense_id = parent.id
    sess = fake_session(
        result(),
        result(Decimal("35.00")),
        result(node),
        gets=[child, None, parent],
    )
    svc = BudgetTreeService(sess)
    out = await svc.update_expense(child.id, ExpenseUpdate(amount=Decimal("35.00")))
    assert out.amount == Decimal("35.00")
    assert parent.amount == Decimal("35.00")


async def test_delete_fiscal_year_ok() -> None:
    """A fiscal year without money rows is deleted.

    The fake session serves the node, the fiscal year, then the three empty guard
    probes.
    """
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
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
    """A fiscal year with applications gives 409.

    ``application.fiscal_year_id`` has no cascade, so an unguarded delete would fail on
    the foreign key with a 500.
    """
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
    sess = fake_session(
        result(top), result(fy), result(), result(), result(uuid.uuid4())
    )
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError) as ei:
        await svc.delete_fiscal_year(top.id, fy.id)
    assert "applications" in str(ei.value)


def _transfer_pair(*, transfer_id=None, src=None, dst=None, fy=None, actor=None):
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


async def test_delete_transfer_missing_income_leg_404() -> None:
    """A booking without its counterpart is no transfer entity, so the delete gives 404."""
    _tid, out, _income = _transfer_pair()
    svc = BudgetTreeService(fake_session(result(out)))
    with pytest.raises(NotFoundError):
        await svc.delete_transfer(uuid.uuid4())


async def test_delete_transfer_missing_expense_leg_404() -> None:
    _tid, _out, income = _transfer_pair()
    svc = BudgetTreeService(fake_session(result(income)))
    with pytest.raises(NotFoundError):
        await svc.delete_transfer(uuid.uuid4())


async def test_path_keys_empty_set_skips_query() -> None:
    svc = BudgetTreeService(fake_session())
    assert await svc._path_keys(set()) == {}


async def test_list_transfers_unfiltered() -> None:
    """The unfiltered list joins the source legs, the income legs and the path keys."""
    tid, out, income = _transfer_pair()
    sess = fake_session(
        result(1),
        result(out),
        result(income),
        result((out.budget_id, "VS-1"), (income.budget_id, "VS-2")),
    )
    page = await BudgetTreeService(sess).list_transfers_paged()
    assert page.total == 1 and page.limit == 50
    assert page.items[0].transfer_id == tid
    assert page.items[0].actor_name is None


async def test_list_transfers_all_filters_and_search() -> None:
    """Every filter and the search apply. The session serves the node, then the count."""
    node = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    tid, out, income = _transfer_pair(actor="u")
    sess = fake_session(
        result(node),
        result(1),
        result(out),
        result(income),
        result((out.budget_id, "VS-1"), (income.budget_id, "VS-2")),
        result(sub_ref("u", "Uwe", None)),
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
    """A blank q adds no search clause, and a nullable date column sorts nulls last."""
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
    """Without a count row or a source leg the total is 0 and no second query runs."""
    sess = fake_session(result(), result())
    page = await BudgetTreeService(sess).list_transfers_paged()
    assert page.total == 0 and page.items == []


async def test_list_transfers_skips_leg_without_counterpart() -> None:
    """A source leg whose income row is gone is no transfer and drops out of the page."""
    _tid, out, _income = _transfer_pair()
    sess = fake_session(result(1), result(out), result())
    page = await BudgetTreeService(sess).list_transfers_paged()
    assert page.total == 1 and page.items == []


async def test_update_transfer_patches_both_legs() -> None:
    """A patch writes the same values to both legs, so the pair never drifts apart.

    The payload may repeat the cost-center pair of the transfer.
    """
    tid, out, income = _transfer_pair(actor="u")
    sess = fake_session(
        result(out, income),
        result((out.budget_id, "VS-1"), (income.budget_id, "VS-2")),
        result(sub_ref("u", "Uwe", None)),
    )
    row = await BudgetTreeService(sess, actor="u").update_transfer(
        tid,
        TransferUpdate(
            amount=Decimal("55.00"),
            description="Korrektur",
            note="Beleg nachgereicht",
            invoiceDate=date(2026, 6, 1),
            paymentDate=date(2026, 6, 2),
            fromBudgetId=out.budget_id,
            toBudgetId=income.budget_id,
        ),
    )
    assert row.amount == Decimal("55.00") and row.note == "Beleg nachgereicht"
    assert income.amount == Decimal("55.00")
    assert income.description == "Korrektur" and income.note == "Beleg nachgereicht"
    assert income.invoice_date == date(2026, 6, 1)
    assert income.payment_date == date(2026, 6, 2)
    assert sess.committed == 1


async def test_update_transfer_audit_entry_is_not_revertable() -> None:
    """The audit entry keeps the prior values under ``prior``, NOT under ``before``.

    A one-sided revert would desync the pair, so the log must not offer it.
    """
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


def _booking_row(inv: Invoice, *, budget_id: uuid.UUID, path: str, name: str) -> tuple:
    booking = _expense(budget_id=budget_id, invoice_id=inv.id, amount="40.00")
    booking.payment_date = date(2026, 3, 1)
    return (booking, path, name)


async def test_list_invoices_paged_carries_linked_bookings_full_view() -> None:
    """The full view lists the linked bookings: counts, count, rows, bookings."""
    inv, other = _invoice(), _invoice(number="R-2")
    bid = uuid.uuid4()
    row = _booking_row(inv, budget_id=bid, path="VS-800", name="Kultur")
    sess = fake_session(counts(2, 1, 1), result(2), result(inv, other), result(row))
    page = await BudgetTreeService(sess).list_invoices_paged()
    first, second = page.items
    assert [b.budget_id for b in first.linked_bookings] == [bid]
    linked = first.linked_bookings[0]
    assert linked.path_key == "VS-800"
    assert linked.budget_name == "Kultur"
    assert linked.amount == Decimal("40.00")
    assert linked.payment_date == date(2026, 3, 1)
    assert linked.kind == "expense"
    assert second.linked_bookings == []


async def test_list_invoices_paged_without_rows_runs_no_booking_query() -> None:
    """An empty page runs no booking query and reads nothing extra.

    The fake session serves the root paths of the member Gremien (none), the counts, the
    count and no rows.
    """
    sess = fake_session(result(), counts(), result(0), result())
    page = await BudgetTreeService(sess).list_invoices_paged(visible_gremium_ids={uuid.uuid4()})
    assert page.items == []
    assert sess._results == []


async def test_get_invoice_scoped_to_member_subtrees() -> None:
    """A scoped read shows the bookings of the member subtrees.

    The fake session serves the root paths of the member Gremien, the subtree ids, then
    the scoped bookings.
    """
    inv = _invoice()
    visible = uuid.uuid4()
    row = _booking_row(inv, budget_id=visible, path="VS-800-04", name="Theater")
    sess = fake_session(result("VS-800"), result(visible), result(row), gets=[inv])
    out = await BudgetTreeService(sess).get_invoice(
        inv.id, visible_gremium_ids={uuid.uuid4()}
    )
    assert [b.budget_id for b in out.linked_bookings] == [visible]


async def test_get_invoice_scope_without_member_gremien_hides_all_bookings() -> None:
    """A reader without member Gremien sees no booking, and no query runs."""
    inv = _invoice()
    sess = fake_session(result(("never-read",)), gets=[inv])
    out = await BudgetTreeService(sess).get_invoice(inv.id, visible_gremium_ids=set())
    assert out.linked_bookings == []
    assert len(sess._results) == 1


async def test_get_invoice_scope_without_view_nodes_hides_all_bookings() -> None:
    """A reader without a root path sees no booking, and the booking query does not run."""
    inv = _invoice()
    sess = fake_session(result(), result(("never-read",)), gets=[inv])
    out = await BudgetTreeService(sess).get_invoice(
        inv.id, visible_gremium_ids={uuid.uuid4()}
    )
    assert out.linked_bookings == []
    assert len(sess._results) == 1


async def test_visible_budget_ids_opens_the_subtrees() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    sess = fake_session(result("VS", "AS-1"), result(a, b))
    assert await BudgetTreeService(sess).visible_budget_ids({uuid.uuid4()}) == {a, b}


async def test_update_invoice_returns_linked_bookings() -> None:
    inv = _invoice()
    bid = uuid.uuid4()
    row = _booking_row(inv, budget_id=bid, path="VS", name="Haushalt")
    sess = fake_session(result(row), gets=[inv])
    out = await BudgetTreeService(sess).update_invoice(inv.id, InvoiceUpdate(note="n"))
    assert [b.budget_id for b in out.linked_bookings] == [bid]
