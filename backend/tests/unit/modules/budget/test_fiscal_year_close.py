"""A closed fiscal year ("abgeschlossen") freezes its money data.

The tests run without a database on the fake session of `test_tree_service_cov`.
They cover the close and the reopen, the guard helpers, and every money mutation
that must answer 409 `fiscal_year_closed` on a closed year.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.audit.actions import AuditAction
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_schemas import (
    AllocationSet,
    AssignBudgetRequest,
    ExpenseCreate,
    ExpenseUpdate,
    FiscalYearUpdate,
    MoveFiscalYearRequest,
    SubBookingCreate,
    TransferUpdate,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from tests.unit.modules.budget.test_tree_service_cov import (
    _app,
    _budget,
    _entry,
    _expense,
    _fy,
    _transfer_pair,
    fake_session,
    result,
)

_CLOSED_AT = datetime(2026, 3, 1, tzinfo=UTC)


def _closed_fy(**kw):
    fy = _fy(**kw)
    fy.closed_at = _CLOSED_AT
    fy.closed_by = "kasse"
    return fy


def _is_closed_error(exc: pytest.ExceptionInfo[ConflictError]) -> bool:
    return exc.value.code == "fiscal_year_closed"


async def test_close_sets_timestamp_actor_and_audit() -> None:
    top = _budget(id=uuid.uuid4())
    fy = _fy(budget_id=top.id)
    sess = fake_session(result(top), result(fy))
    out = await BudgetTreeService(sess, actor="kasse").set_fiscal_year_closed(
        top.id, fy.id, closed=True, actor="kasse"
    )
    assert fy.closed_at is not None and fy.closed_by == "kasse"
    assert out.closed_at == fy.closed_at
    assert sess.committed == 1
    assert [a.action for a in sess.added] == [AuditAction.BUDGET_FISCAL_YEAR_CLOSE]


async def test_reopen_clears_the_close() -> None:
    top = _budget(id=uuid.uuid4())
    fy = _closed_fy(budget_id=top.id)
    sess = fake_session(result(top), result(fy))
    out = await BudgetTreeService(sess, actor="kasse").set_fiscal_year_closed(
        top.id, fy.id, closed=False, actor="kasse"
    )
    assert fy.closed_at is None and fy.closed_by is None
    assert out.closed_at is None
    assert [a.action for a in sess.added] == [AuditAction.BUDGET_FISCAL_YEAR_REOPEN]


async def test_close_of_a_closed_year_changes_nothing() -> None:
    top = _budget(id=uuid.uuid4())
    fy = _closed_fy(budget_id=top.id)
    sess = fake_session(result(top), result(fy))
    out = await BudgetTreeService(sess).set_fiscal_year_closed(
        top.id, fy.id, closed=True, actor="other"
    )
    assert fy.closed_at == _CLOSED_AT and fy.closed_by == "kasse"
    assert out.closed_at == _CLOSED_AT
    assert sess.committed == 0 and sess.added == []


async def test_close_of_a_foreign_year_404() -> None:
    top = _budget(id=uuid.uuid4())
    foreign = _fy(budget_id=uuid.uuid4())
    svc = BudgetTreeService(fake_session(result(top), result(foreign)))
    with pytest.raises(NotFoundError):
        await svc.set_fiscal_year_closed(top.id, foreign.id, closed=True, actor="k")


async def test_close_below_top_level_422() -> None:
    child = _budget(id=uuid.uuid4(), parent_id=uuid.uuid4(), path_key="VS-1", key="1")
    svc = BudgetTreeService(fake_session(result(child)))
    with pytest.raises(ValidationProblem):
        await svc.set_fiscal_year_closed(child.id, uuid.uuid4(), closed=True, actor="k")


async def test_list_reports_closed_at() -> None:
    top = _budget(id=uuid.uuid4())
    fy = _closed_fy(budget_id=top.id)
    out = await BudgetTreeService(fake_session(result(top), result(fy))).list_fiscal_years(
        top.id
    )
    assert out[0].closed_at == _CLOSED_AT


async def test_year_change_on_closed_year_409() -> None:
    top = _budget(id=uuid.uuid4())
    fy = _closed_fy(budget_id=top.id, year=2025)
    svc = BudgetTreeService(fake_session(result(top), result(fy)))
    with pytest.raises(ConflictError) as ei:
        await svc.update_fiscal_year(top.id, fy.id, FiscalYearUpdate(year=2024))
    assert _is_closed_error(ei)
    assert fy.year == 2025


async def test_same_year_and_active_flag_on_closed_year_ok() -> None:
    top = _budget(id=uuid.uuid4())
    fy = _closed_fy(budget_id=top.id, year=2025)
    sess = fake_session(result(top), result(fy))
    out = await BudgetTreeService(sess).update_fiscal_year(
        top.id, fy.id, FiscalYearUpdate(year=2025, active=False)
    )
    assert out.active is False and fy.year == 2025


async def test_delete_closed_year_409() -> None:
    top = _budget(id=uuid.uuid4())
    fy = _closed_fy(budget_id=top.id)
    sess = fake_session(result(top), result(fy))
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess).delete_fiscal_year(top.id, fy.id)
    assert _is_closed_error(ei)
    assert sess.deleted == []


async def test_require_open_passes_none_missing_and_open() -> None:
    """No year (no lookup at all), a missing row and an open year pass."""
    svc = BudgetTreeService(fake_session(gets=[None, _fy()]))
    await svc._require_open_fiscal_year(None)
    await svc._require_open_fiscal_year(uuid.uuid4())
    await svc._require_open_fiscal_year(uuid.uuid4())


async def test_require_open_refuses_closed() -> None:
    svc = BudgetTreeService(fake_session(gets=[_closed_fy()]))
    with pytest.raises(ConflictError) as ei:
        await svc._require_open_fiscal_year(uuid.uuid4())
    assert _is_closed_error(ei)


async def test_resolve_explicit_closed_year_409() -> None:
    top = _budget(id=uuid.uuid4())
    fy = _closed_fy(budget_id=top.id)
    svc = BudgetTreeService(fake_session(result(top), result(fy)))
    with pytest.raises(ConflictError) as ei:
        await svc._resolve_fiscal_year(top, fy.id)
    assert _is_closed_error(ei)


async def test_resolve_default_skips_closed_year() -> None:
    """Two active years, one of them closed: the open one is the single default."""
    top = _budget(id=uuid.uuid4())
    closed = _closed_fy(budget_id=top.id, year=2025)
    open_ = _fy(budget_id=top.id, year=2026)
    svc = BudgetTreeService(fake_session(result(top), result(closed, open_)))
    assert await svc._resolve_fiscal_year(top, None) == open_.id


async def test_book_expense_for_application_in_closed_year_409() -> None:
    node = _budget(id=uuid.uuid4())
    fy = _closed_fy(budget_id=node.id)
    app = _app(budget_id=node.id, fiscal_year_id=fy.id)
    sess = fake_session(result(node), gets=[app, fy])
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess).book_expense(
            ExpenseCreate(applicationId=app.id, amount=Decimal("5"), description="x"),
            actor="u",
        )
    assert _is_closed_error(ei)
    assert sess.added == []


async def test_update_expense_in_closed_year_409() -> None:
    fy = _closed_fy()
    expense = _expense(fy_id=fy.id)
    sess = fake_session(gets=[expense, fy])
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess).update_expense(expense.id, ExpenseUpdate(note="n"))
    assert _is_closed_error(ei)
    assert sess.committed == 0


async def test_delete_expense_in_closed_year_409() -> None:
    fy = _closed_fy()
    expense = _expense(fy_id=fy.id)
    sess = fake_session(result(expense), gets=[fy])
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess).delete_expense(expense.id)
    assert _is_closed_error(ei)
    assert sess.deleted == []


async def test_sub_booking_in_closed_year_409() -> None:
    fy = _closed_fy()
    parent = _expense(fy_id=fy.id)
    sess = fake_session(gets=[parent, fy])
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess).create_sub_booking(
            parent.id, SubBookingCreate(amount=Decimal("1"), description="x"), actor="u"
        )
    assert _is_closed_error(ei)
    assert sess.added == []


async def test_update_transfer_in_closed_year_409() -> None:
    fy = _closed_fy()
    tid, out, income = _transfer_pair(fy=fy.id)
    sess = fake_session(result(out, income), gets=[fy])
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess).update_transfer(tid, TransferUpdate(note="n"))
    assert _is_closed_error(ei)
    assert sess.committed == 0


async def test_delete_transfer_in_closed_year_409() -> None:
    fy = _closed_fy()
    tid, out, income = _transfer_pair(fy=fy.id)
    sess = fake_session(result(out, income), gets=[fy])
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess).delete_transfer(tid)
    assert _is_closed_error(ei)
    assert sess.deleted == []


async def test_set_allocation_in_closed_year_409() -> None:
    top = _budget(id=uuid.uuid4())
    fy = _closed_fy(budget_id=top.id)
    sess = fake_session(result(top), result(fy), result(top))
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess).set_allocation(
            top.id, fy.id, AllocationSet(allocated=Decimal("100"))
        )
    assert _is_closed_error(ei)
    assert sess.added == []


async def test_assign_budget_out_of_closed_year_409() -> None:
    fy = _closed_fy()
    app = _app(budget_id=uuid.uuid4(), fiscal_year_id=fy.id)
    sess = fake_session(result(app), gets=[fy])
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess).assign_budget(app.id, AssignBudgetRequest(budgetId=None))
    assert _is_closed_error(ei)
    assert app.budget_id is not None and app.fiscal_year_id == fy.id


async def test_move_out_of_closed_year_409() -> None:
    top = _budget(id=uuid.uuid4())
    current = _closed_fy(budget_id=top.id, year=2025)
    target = _fy(budget_id=top.id, year=2026)
    app = _app(budget_id=top.id, fiscal_year_id=current.id)
    sess = fake_session(result(app), result(top), result(top), result(target), gets=[current])
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess).move_fiscal_year(
            app.id, MoveFiscalYearRequest(fiscalYearId=target.id)
        )
    assert _is_closed_error(ei)
    assert app.fiscal_year_id == current.id


async def test_move_into_closed_year_409() -> None:
    top = _budget(id=uuid.uuid4())
    target = _closed_fy(budget_id=top.id, year=2025)
    app = _app(budget_id=top.id, fiscal_year_id=uuid.uuid4())
    sess = fake_session(result(app), result(top), result(top), result(target), gets=[None])
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess).move_fiscal_year(
            app.id, MoveFiscalYearRequest(fiscalYearId=target.id)
        )
    assert _is_closed_error(ei)


async def test_revert_booking_in_closed_year_409() -> None:
    fy = _closed_fy()
    expense = _expense(fy_id=fy.id)
    sess = fake_session(gets=[expense, fy])
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess, actor="admin").revert_audit(
            _entry(AuditAction.BUDGET_EXPENSE_CREATE, expense.id), "admin"
        )
    assert _is_closed_error(ei)
    assert sess.deleted == []


async def test_revert_transfer_in_closed_year_409() -> None:
    fy = _closed_fy()
    tid, out, income = _transfer_pair(fy=fy.id)
    sess = fake_session(result(out, income), gets=[fy])
    with pytest.raises(ConflictError) as ei:
        await BudgetTreeService(sess, actor="admin").revert_audit(
            _entry(AuditAction.BUDGET_TRANSFER_CREATE, tid), "admin"
        )
    assert _is_closed_error(ei)
    assert sess.deleted == []
