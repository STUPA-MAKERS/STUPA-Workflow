"""BudgetTreeService without a DB. A fake session covers every branch (100 %).

The order of the `execute` results mirrors the service flow. Each `execute` pops one entry
from a FIFO queue. See `tests/auth_fakes.FakeSession`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.modules.admin.models import Gremium
from app.modules.applications.models import Application
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_models import (
    Budget,
    BudgetAllocation,
    BudgetExpense,
    FiscalYear,
)
from app.modules.budget.tree_schemas import (
    AllocationSet,
    AssignBudgetRequest,
    BudgetNodeCreate,
    BudgetNodeUpdate,
    FiscalYearCreate,
    FiscalYearUpdate,
    MoveFiscalYearRequest,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from tests._support.auth_fakes import fake_session, result


def _budget(
    *, id=None, parent_id=None, path_key="VS", gremium_id=None, key="VS", name="N",
    fiscal_start_month=1, fiscal_start_day=1,
):
    b = Budget(
        parent_id=parent_id, gremium_id=gremium_id, key=key,
        path_key=path_key, name=name, currency="EUR", active=True,
        fiscal_start_month=fiscal_start_month, fiscal_start_day=fiscal_start_day,
    )
    b.id = id or uuid.uuid4()
    return b


def _fy(*, id=None, budget_id=None, year=2026, active=True):
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    f = FiscalYear(budget_id=budget_id, year=year, start_date=start, end_date=end, active=active)
    f.id = id or uuid.uuid4()
    return f


def _alloc(*, budget_id, fy_id, allocated):
    a = BudgetAllocation(budget_id=budget_id, fiscal_year_id=fy_id, allocated=Decimal(allocated))
    a.id = uuid.uuid4()
    return a


def _app(*, id=None, budget_id=None, fiscal_year_id=None, amount=None):
    a = Application(
        type_id=uuid.uuid4(), form_version_id=uuid.uuid4(), flow_version_id=uuid.uuid4(),
        budget_id=budget_id, fiscal_year_id=fiscal_year_id, amount=amount, data={},
    )
    a.id = id or uuid.uuid4()
    return a


async def test_create_node_invalid_key() -> None:
    svc = BudgetTreeService(fake_session())
    with pytest.raises(ValidationProblem):
        await svc.create_node(BudgetNodeCreate(key="VS-800", name="x"))


async def test_create_top_level_without_gremium_ok() -> None:
    """A top-level node needs no gremiumId, because a budget does not belong to a Gremium.

    The fake session serves only the sibling check, no Gremium lookup.
    """
    sess = fake_session(result())
    svc = BudgetTreeService(sess)
    out = await svc.create_node(BudgetNodeCreate(key="VS", name="VS-Mittel"))
    assert out.path_key == "VS" and out.gremium_id is None


async def test_create_top_level_gremium_not_found() -> None:
    """An unknown gremiumId on a top-level node gives 404."""
    svc = BudgetTreeService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc.create_node(
            BudgetNodeCreate(key="VS", name="x", gremiumId=uuid.uuid4())
        )


async def test_create_top_level_ok() -> None:
    """A top-level node with a known Gremium and no sibling is created."""
    g = Gremium(name="G", slug="g")
    g.id = uuid.uuid4()
    sess = fake_session(result(g), result())
    svc = BudgetTreeService(sess)
    out = await svc.create_node(BudgetNodeCreate(key="VS", name="VS-Mittel", gremiumId=g.id))
    assert out.path_key == "VS" and out.gremium_id == g.id
    assert sess.committed == 1


async def test_create_child_inherits_gremium_and_path() -> None:
    """A child inherits the Gremium and the path prefix of its parent."""
    g = uuid.uuid4()
    parent = _budget(path_key="VS", gremium_id=g)
    sess = fake_session(result(parent), result())
    svc = BudgetTreeService(sess)
    out = await svc.create_node(
        BudgetNodeCreate(key="800", name="Dezentral", parentId=parent.id)
    )
    assert out.path_key == "VS-800" and out.gremium_id == g


async def test_create_child_parent_not_found() -> None:
    svc = BudgetTreeService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc.create_node(BudgetNodeCreate(key="800", name="x", parentId=uuid.uuid4()))


async def test_create_node_duplicate_key() -> None:
    parent = _budget(path_key="VS", gremium_id=uuid.uuid4())
    existing = _budget(path_key="VS-800", parent_id=parent.id, key="800")
    sess = fake_session(result(parent), result(existing))
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError):
        await svc.create_node(BudgetNodeCreate(key="800", name="x", parentId=parent.id))


async def test_update_node() -> None:
    node = _budget()
    sess = fake_session(result(node))
    svc = BudgetTreeService(sess)
    out = await svc.update_node(node.id, BudgetNodeUpdate(name="Neu", active=False))
    assert out.name == "Neu" and out.active is False


async def test_update_node_not_found() -> None:
    svc = BudgetTreeService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc.update_node(uuid.uuid4(), BudgetNodeUpdate(name="x"))


async def test_update_node_stichtag_rederives_fiscal_years() -> None:
    """A new cut-off date on the top budget re-derives start and end of every fiscal year.

    The fake session serves ``_get_node`` and ``_fiscal_years_of``.
    """
    top = _budget(path_key="VS", fiscal_start_month=1, fiscal_start_day=1)
    fy = _fy(budget_id=top.id, year=2026)
    sess = fake_session(result(top), result(fy))
    svc = BudgetTreeService(sess)
    out = await svc.update_node(top.id, BudgetNodeUpdate(fiscalStartMonth=7, fiscalStartDay=1))
    assert out.fiscal_start_month == 7 and out.fiscal_start_day == 1
    assert fy.start_date == date(2026, 7, 1) and fy.end_date == date(2027, 6, 30)


async def test_update_node_stichtag_unchanged_skips_rederive() -> None:
    """The same cut-off value skips the fiscal-year re-derive. Only the name changes."""
    top = _budget(path_key="VS", fiscal_start_month=1, fiscal_start_day=1)
    sess = fake_session(result(top))
    svc = BudgetTreeService(sess)
    out = await svc.update_node(top.id, BudgetNodeUpdate(name="Neu", fiscalStartMonth=1))
    assert out.name == "Neu" and out.fiscal_start_month == 1


async def test_delete_node_ok() -> None:
    """A node without child, booking or assigned application is deleted.

    Any allocation cascades away with the node, so the delete proceeds.
    """
    node = _budget()
    sess = fake_session(result(node), result(), result(), result())
    svc = BudgetTreeService(sess)
    await svc.delete_node(node.id)
    assert sess.deleted == [node]


async def test_delete_node_with_children() -> None:
    """A node with a child cannot be deleted."""
    node = _budget()
    sess = fake_session(result(node), result(uuid.uuid4()))
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError):
        await svc.delete_node(node.id)


async def test_delete_node_with_bookings() -> None:
    """A childless cost center with bookings must not be silently cascade-wiped."""
    node = _budget()
    sess = fake_session(result(node), result(), result(uuid.uuid4()))
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError):
        await svc.delete_node(node.id)


async def test_delete_node_with_assigned_applications() -> None:
    """A cost center with an assigned application cannot be deleted, because it would orphan it."""
    node = _budget()
    sess = fake_session(result(node), result(), result(), result(uuid.uuid4()))
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError):
        await svc.delete_node(node.id)


async def test_delete_node_with_allocation_only_succeeds() -> None:
    """A leaf with only an allocation row (a planning figure) can be deleted.

    It has no children, bookings or applications, so the guard must not block it.
    """
    node = _budget()
    sess = fake_session(result(node), result(), result(), result())
    svc = BudgetTreeService(sess)
    await svc.delete_node(node.id)
    assert sess.deleted == [node]


async def test_delete_node_not_found() -> None:
    svc = BudgetTreeService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc.delete_node(uuid.uuid4())


async def test_list_fiscal_years_resolves_top_ancestor() -> None:
    """A node below the top level resolves to its top-level ancestor.

    A scoped root is often a sub cost center.
    """
    top = _budget(path_key="VS")
    child = _budget(parent_id=top.id, path_key="VS-800")
    fy = _fy(budget_id=top.id)
    svc = BudgetTreeService(fake_session(result(child), result(top), result(fy)))
    out = await svc.list_fiscal_years(child.id)
    assert len(out) == 1 and out[0].budget_id == top.id


async def test_list_fiscal_years_ok() -> None:
    top = _budget(path_key="VS")
    fy = _fy(budget_id=top.id)
    sess = fake_session(result(top), result(fy))
    svc = BudgetTreeService(sess)
    out = await svc.list_fiscal_years(top.id)
    assert len(out) == 1 and out[0].budget_id == top.id
    assert out[0].year == 2026 and out[0].display == "2026"


async def test_create_fiscal_year_ok() -> None:
    """A top-level node without fiscal years gets the new year."""
    top = _budget(path_key="VS")
    sess = fake_session(result(top), result())
    svc = BudgetTreeService(sess)
    out = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    assert out.year == 2026 and out.display == "2026"
    assert out.start_date == date(2026, 1, 1) and out.end_date == date(2026, 12, 31)
    assert sess.committed == 1


async def test_create_fiscal_year_offset_stichtag_display() -> None:
    """A cut-off of 01.07. gives the period 01.07.2026 to 30.06.2027 and the label '2026/27'."""
    top = _budget(path_key="VS", fiscal_start_month=7, fiscal_start_day=1)
    sess = fake_session(result(top), result())
    svc = BudgetTreeService(sess)
    out = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    assert out.display == "2026/27"
    assert out.start_date == date(2026, 7, 1) and out.end_date == date(2027, 6, 30)


async def test_create_fiscal_year_duplicate_year() -> None:
    top = _budget(path_key="VS")
    existing = _fy(budget_id=top.id, year=2026)
    sess = fake_session(result(top), result(existing))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))


async def test_update_fiscal_year_active_only() -> None:
    """A change of the active flag only does not check the year for uniqueness.

    The fake session serves ``_require_top_level`` and ``_get_fiscal_year``. The year
    does not change, so ``_fiscal_years_of`` does not run.
    """
    top = _budget(path_key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    sess = fake_session(result(top), result(fy))
    svc = BudgetTreeService(sess)
    out = await svc.update_fiscal_year(top.id, fy.id, FiscalYearUpdate(active=False))
    assert out.active is False and out.year == 2026


async def test_update_fiscal_year_change_year_rederives_dates() -> None:
    """A new year re-derives the dates and checks the year for uniqueness.

    The fake session serves ``_require_top_level``, ``_get_fiscal_year`` and
    ``_fiscal_years_of``.
    """
    top = _budget(path_key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, year=2026)
    sess = fake_session(result(top), result(fy), result(fy))
    svc = BudgetTreeService(sess)
    out = await svc.update_fiscal_year(top.id, fy.id, FiscalYearUpdate(year=2027))
    assert out.year == 2027
    assert out.start_date == date(2027, 1, 1) and out.end_date == date(2027, 12, 31)


async def test_update_fiscal_year_duplicate_year() -> None:
    top = _budget(path_key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, year=2026)
    other = _fy(id=uuid.uuid4(), budget_id=top.id, year=2027)
    sess = fake_session(result(top), result(fy), result(fy, other))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.update_fiscal_year(top.id, fy.id, FiscalYearUpdate(year=2027))


async def test_set_allocation_fy_mismatch() -> None:
    """A fiscal year of another top budget gives 422."""
    node = _budget(path_key="VS")
    top = node
    fy = _fy(budget_id=uuid.uuid4())
    sess = fake_session(result(node), result(fy), result(top))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(node.id, fy.id, AllocationSet(allocated=Decimal("100")))


async def test_set_allocation_top_level_new() -> None:
    """A top-level allocation creates a new row.

    The fake session serves the node, the fiscal year, the top, the lock of the node, no
    own children and no allocation of the node.
    """
    top = _budget(path_key="VS")
    fy = _fy(budget_id=top.id)
    sess = fake_session(result(top), result(fy), result(top), result(), result(), result())
    svc = BudgetTreeService(sess)
    out = await svc.set_allocation(top.id, fy.id, AllocationSet(allocated=Decimal("1000")))
    assert out.allocated == Decimal("1000") and sess.committed == 1


async def test_set_allocation_child_exceeds_parent() -> None:
    """A child allocation above the free parent allocation gives 422.

    The other children hold 600, so 600 + 500 = 1100 exceeds 1000. The fake session
    serves the node, the fiscal year, the top, the locks of the node and the parent, the
    siblings and the parent allocation.
    """
    parent = _budget(path_key="VS")
    child = _budget(parent_id=parent.id, path_key="VS-800", key="800")
    top = parent
    fy = _fy(budget_id=top.id)
    sibling_rows = result((uuid.uuid4(), Decimal("600")))
    parent_alloc = _alloc(budget_id=parent.id, fy_id=fy.id, allocated="1000")
    sess = fake_session(
        result(child), result(fy), result(top), result(), result(),
        sibling_rows, result(parent_alloc),
    )
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(child.id, fy.id, AllocationSet(allocated=Decimal("500")))


async def test_set_allocation_child_ok_update_existing() -> None:
    """A child allocation within the parent allocation updates the existing row.

    The child is a leaf without own children. The fake session serves the node, the
    fiscal year, the top, the locks of the node and the parent, the siblings, the parent
    allocation, the own children and the allocation of the node.
    """
    parent = _budget(path_key="VS")
    child = _budget(parent_id=parent.id, path_key="VS-800", key="800")
    top = parent
    fy = _fy(budget_id=top.id)
    sibling_rows = result((uuid.uuid4(), Decimal("100")))
    parent_alloc = _alloc(budget_id=parent.id, fy_id=fy.id, allocated="1000")
    own_children = result()
    self_alloc = _alloc(budget_id=child.id, fy_id=fy.id, allocated="200")
    sess = fake_session(
        result(child), result(fy), result(top), result(), result(), sibling_rows,
        result(parent_alloc), own_children, result(self_alloc),
    )
    svc = BudgetTreeService(sess)
    out = await svc.set_allocation(child.id, fy.id, AllocationSet(allocated=Decimal("300")))
    assert out.allocated == Decimal("300")
    assert self_alloc.allocated == Decimal("300")


async def test_set_allocation_below_children() -> None:
    """An allocation below the 700 already given to the children gives 422.

    The fake session serves the node, the fiscal year, the top, the lock of the node and
    the own children.
    """
    top = _budget(path_key="VS")
    fy = _fy(budget_id=top.id)
    own_children = result((uuid.uuid4(), Decimal("700")))
    sess = fake_session(result(top), result(fy), result(top), result(), own_children)
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(top.id, fy.id, AllocationSet(allocated=Decimal("500")))


async def test_set_allocation_fy_not_found() -> None:
    """An unknown fiscal year gives 404."""
    node = _budget(path_key="VS")
    sess = fake_session(result(node), result())
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.set_allocation(node.id, uuid.uuid4(), AllocationSet(allocated=Decimal("1")))


async def test_set_allocation_top_not_found() -> None:
    """A missing top-level node gives 404."""
    node = _budget(path_key="VS")
    fy = _fy(budget_id=node.id)
    sess = fake_session(result(node), result(fy), result())
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.set_allocation(node.id, fy.id, AllocationSet(allocated=Decimal("1")))


async def test_children_alloc_sum_excludes_self() -> None:
    """The sibling sum ignores the row of the node itself.

    The siblings give 100, plus 300 gives 400, which stays under 1000, because the
    service skips the 999 row of the node. The fake session serves the node, the fiscal
    year, the top, the locks of the node and the parent, the siblings, the parent
    allocation, the own children and the allocation of the node.
    """
    parent = _budget(path_key="VS")
    child = _budget(parent_id=parent.id, path_key="VS-800", key="800")
    top = parent
    fy = _fy(budget_id=top.id)
    sibling_rows = result((child.id, Decimal("999")), (uuid.uuid4(), Decimal("100")))
    parent_alloc = _alloc(budget_id=parent.id, fy_id=fy.id, allocated="1000")
    sess = fake_session(
        result(child), result(fy), result(top), result(), result(), sibling_rows,
        result(parent_alloc), result(), result(),
    )
    svc = BudgetTreeService(sess)
    out = await svc.set_allocation(child.id, fy.id, AllocationSet(allocated=Decimal("300")))
    assert out.allocated == Decimal("300")


async def test_set_allocation_child_no_parent_alloc() -> None:
    """A child allocation without a parent allocation gives 422 (0 + 1 > 0).

    There are no other children. The fake session serves the node, the fiscal year, the
    top, the locks of the node and the parent, the siblings and no parent allocation.
    """
    parent = _budget(path_key="VS")
    child = _budget(parent_id=parent.id, path_key="VS-800", key="800")
    top = parent
    fy = _fy(budget_id=top.id)
    sibling_rows = result()
    sess = fake_session(
        result(child), result(fy), result(top), result(), result(), sibling_rows, result(),
    )
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(child.id, fy.id, AllocationSet(allocated=Decimal("1")))


async def test_assign_budget_clear() -> None:
    app = _app(budget_id=uuid.uuid4(), fiscal_year_id=uuid.uuid4())
    sess = fake_session(result(app))
    svc = BudgetTreeService(sess)
    out = await svc.assign_budget(app.id, AssignBudgetRequest(budgetId=None))
    assert out.budget_id is None and out.fiscal_year_id is None
    assert app.budget_id is None and app.fiscal_year_id is None


async def test_assign_budget_sets_fiscal_year() -> None:
    """The assignment takes the single active fiscal year of the top budget.

    The fake session serves the application, the node, the top and the fiscal years.
    """
    top = _budget(path_key="VS")
    node = top
    fy = _fy(budget_id=top.id, active=True)
    app = _app()
    sess = fake_session(result(app), result(node), result(top), result(fy))
    svc = BudgetTreeService(sess)
    out = await svc.assign_budget(app.id, AssignBudgetRequest(budgetId=node.id))
    assert out.budget_id == node.id and out.fiscal_year_id == fy.id


async def test_assign_budget_app_not_found() -> None:
    svc = BudgetTreeService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc.assign_budget(uuid.uuid4(), AssignBudgetRequest(budgetId=uuid.uuid4()))


async def test_assign_budget_explicit_fiscal_year() -> None:
    """An explicit fiscal year of the top budget is taken.

    The fake session serves ``_get_application``, ``_get_node``, ``_top_level`` and
    ``_get_fiscal_year``.
    """
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    app = _app()
    sess = fake_session(result(app), result(node), result(top), result(fy))
    svc = BudgetTreeService(sess)
    out = await svc.assign_budget(
        app.id, AssignBudgetRequest(budgetId=node.id, fiscalYearId=fy.id)
    )
    assert out.budget_id == node.id and out.fiscal_year_id == fy.id


async def test_assign_budget_ambiguous_requires_fiscal_year() -> None:
    """Two active fiscal years without an explicit fiscalYearId give 422, not a silent NULL.

    The fake session serves ``_get_application``, ``_get_node``, ``_top_level`` and
    ``_fiscal_years_of``.
    """
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy1 = _fy(id=uuid.uuid4(), budget_id=top.id)
    fy2 = _fy(id=uuid.uuid4(), budget_id=top.id)
    app = _app()
    sess = fake_session(result(app), result(node), result(top), result(fy1, fy2))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.assign_budget(app.id, AssignBudgetRequest(budgetId=node.id))


async def test_move_fiscal_year_ok() -> None:
    top = _budget(path_key="VS")
    node = top
    fy = _fy(budget_id=top.id)
    app = _app(budget_id=node.id, fiscal_year_id=uuid.uuid4())
    sess = fake_session(result(app), result(node), result(top), result(fy))
    svc = BudgetTreeService(sess)
    out = await svc.move_fiscal_year(app.id, MoveFiscalYearRequest(fiscalYearId=fy.id))
    assert out.fiscal_year_id == fy.id


async def test_move_fiscal_year_no_budget() -> None:
    app = _app()
    svc = BudgetTreeService(fake_session(result(app)))
    with pytest.raises(ValidationProblem):
        await svc.move_fiscal_year(app.id, MoveFiscalYearRequest(fiscalYearId=uuid.uuid4()))


async def test_move_fiscal_year_wrong_top() -> None:
    """A fiscal year of another top budget gives 422."""
    top = _budget(path_key="VS")
    node = top
    fy = _fy(budget_id=uuid.uuid4())
    app = _app(budget_id=node.id)
    sess = fake_session(result(app), result(node), result(top), result(fy))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.move_fiscal_year(app.id, MoveFiscalYearRequest(fiscalYearId=fy.id))


async def test_get_tree_assembles() -> None:
    """The tree classifies applications by the state keys of the top budget.

    An application in an accepted state counts as bound (250), a submitted one as
    requested (120), and a rejected one drops out (999). Committed is bound plus
    expended. The fake session serves the nodes, the allocations, the application rows
    (id, path, fiscal year, amount, committed, state) and no expense rows.
    """
    g = uuid.uuid4()
    fy_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", gremium_id=g, key="VS")
    top.accepted_state_keys = ["approved"]
    top.denied_state_keys = ["rejected"]
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    sess = fake_session(
        result(top),
        result(alloc),
        result(
            (uuid.uuid4(), "VS", fy_id, Decimal("250"), Decimal("250"), "approved"),
            (uuid.uuid4(), "VS", fy_id, Decimal("120"), Decimal("120"), "submitted"),
            (uuid.uuid4(), "VS", fy_id, Decimal("999"), Decimal("999"), "rejected"),
        ),
        result(),
    )
    svc = BudgetTreeService(sess)
    tree = await svc.get_tree()
    assert len(tree) == 1
    view = tree[0].by_fiscal_year[0]
    assert view.allocated == Decimal("1000")
    assert view.bound == Decimal("250")
    assert view.expended == Decimal("0")
    assert view.committed == Decimal("250")
    assert view.requested == Decimal("120")
    assert view.available == Decimal("750")


async def test_get_tree_binds_the_approved_amount() -> None:
    """An accepted application binds its approved amount, not the requested one."""
    fy_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", gremium_id=uuid.uuid4(), key="VS")
    top.accepted_state_keys = ["approved"]
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    sess = fake_session(
        result(top),
        result(alloc),
        result(
            (uuid.uuid4(), "VS", fy_id, Decimal("250"), Decimal("200"), "approved"),
            (uuid.uuid4(), "VS", fy_id, Decimal("120"), Decimal("120"), "submitted"),
        ),
        result(),
    )
    view = (await BudgetTreeService(sess).get_tree())[0].by_fiscal_year[0]
    assert view.bound == Decimal("200")
    assert view.requested == Decimal("120")
    assert view.available == Decimal("800")


async def test_get_tree_rolls_up_standalone_expenses() -> None:
    """Standalone expenses count as expended, not as bound.

    The fake session serves the nodes, the allocations, no application rows and one
    standalone expense of 60, which is committed (bound plus expended).
    """
    g = uuid.uuid4()
    fy_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", gremium_id=g, key="VS")
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    sess = fake_session(
        result(top),
        result(alloc),
        result(),
        result(("VS", fy_id, Decimal("60"), "expense", None)),
    )
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.bound == Decimal("0")
    assert view.expended == Decimal("60")
    assert view.committed == Decimal("60")
    assert view.available == Decimal("940")


async def test_get_tree_income_increases_available() -> None:
    """Income raises the available budget.

    An income of 200 gives available = 1000 − 0 − 0 + 200.
    """
    fy_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    sess = fake_session(
        result(top),
        result(alloc),
        result(),
        result(("VS", fy_id, Decimal("200"), "income", None)),
    )
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.income == Decimal("200")
    assert view.expended == Decimal("0")
    assert view.available == Decimal("1200")


async def test_get_tree_linked_expense_replaces_bound() -> None:
    """An expense linked to an application replaces that binding in proportion.

    An approved application of 250 has 100 spent on it. Bound is 250 − 100 = 150,
    committed stays the original binding of 250, and available is 1000 − 150 − 100 =
    750.
    """
    fy_id = uuid.uuid4()
    app_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top.accepted_state_keys = ["approved"]
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    sess = fake_session(
        result(top),
        result(alloc),
        result((app_id, "VS", fy_id, Decimal("250"), Decimal("250"), "approved")),
        result(("VS", fy_id, Decimal("100"), "expense", app_id)),
    )
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.bound == Decimal("150")
    assert view.expended == Decimal("100")
    assert view.committed == Decimal("250")
    assert view.available == Decimal("750")


async def test_resolve_fiscal_year_explicit_ok() -> None:
    """An explicit fiscal year of the top budget resolves."""
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
    sess = fake_session(result(top), result(fy))
    svc = BudgetTreeService(sess)
    assert await svc._resolve_fiscal_year(node, fy.id) == fy.id


async def test_resolve_fiscal_year_wrong_top() -> None:
    """A fiscal year of another top budget gives 422."""
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy = _fy(id=uuid.uuid4(), budget_id=uuid.uuid4())
    sess = fake_session(result(top), result(fy))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc._resolve_fiscal_year(node, fy.id)


async def test_resolve_fiscal_year_ambiguous() -> None:
    """Two fiscal years without an explicit choice give 422."""
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy1 = _fy(id=uuid.uuid4(), budget_id=top.id)
    fy2 = _fy(id=uuid.uuid4(), budget_id=top.id)
    sess = fake_session(result(top), result(fy1, fy2))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc._resolve_fiscal_year(node, None)


async def test_delete_expense_not_found() -> None:
    svc = BudgetTreeService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc.delete_expense(uuid.uuid4())


def test_expense_out_maps_metadata_fields() -> None:
    """The extra metadata reaches the output DTO in camelCase."""
    e = BudgetExpense(
        id=uuid.uuid4(),
        budget_id=uuid.uuid4(),
        fiscal_year_id=uuid.uuid4(),
        kind="expense",
        amount=Decimal("10.00"),
        currency="EUR",
        description="x",
        invoice_date=date(2026, 1, 2),
        payment_date=date(2026, 1, 9),
        correspondent="ACME GmbH",
        note="mehrzeilige\nAnmerkung",
        reference_number="R-2026-1",
        payment_method="ueberweisung",
        category="Reise",
    )
    e.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    out = BudgetTreeService._expense_out(e, "VS")
    d = out.model_dump(by_alias=True)
    assert d["invoiceDate"] == date(2026, 1, 2)
    assert d["paymentDate"] == date(2026, 1, 9)
    assert d["correspondent"] == "ACME GmbH"
    assert d["note"] == "mehrzeilige\nAnmerkung"
    assert d["referenceNumber"] == "R-2026-1"
    assert d["paymentMethod"] == "ueberweisung"
    assert d["category"] == "Reise"
