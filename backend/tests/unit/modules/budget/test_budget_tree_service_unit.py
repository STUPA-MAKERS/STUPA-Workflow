"""BudgetTreeService (CR #76/#78) without a DB. A fake session covers every branch (100 %).

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


def _budget(  # noqa: ANN001
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


def _fy(*, id=None, budget_id=None, year=2026, active=True):  # noqa: ANN001
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    f = FiscalYear(budget_id=budget_id, year=year, start_date=start, end_date=end, active=active)
    f.id = id or uuid.uuid4()
    return f


def _alloc(*, budget_id, fy_id, allocated):  # noqa: ANN001
    a = BudgetAllocation(budget_id=budget_id, fiscal_year_id=fy_id, allocated=Decimal(allocated))
    a.id = uuid.uuid4()
    return a


def _app(*, id=None, budget_id=None, fiscal_year_id=None, amount=None):  # noqa: ANN001
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
    # #22: a budget does not belong to a Gremium. A top-level node needs no gremiumId.
    sess = fake_session(result())  # only the sibling check, no Gremium lookup
    svc = BudgetTreeService(sess)
    out = await svc.create_node(BudgetNodeCreate(key="VS", name="VS-Mittel"))
    assert out.path_key == "VS" and out.gremium_id is None


async def test_create_top_level_gremium_not_found() -> None:
    svc = BudgetTreeService(fake_session(result()))  # gremium lookup returns None
    with pytest.raises(NotFoundError):
        await svc.create_node(
            BudgetNodeCreate(key="VS", name="x", gremiumId=uuid.uuid4())
        )


async def test_create_top_level_ok() -> None:
    g = Gremium(name="G", slug="g")
    g.id = uuid.uuid4()
    sess = fake_session(result(g), result())  # gremium found, no sibling
    svc = BudgetTreeService(sess)
    out = await svc.create_node(BudgetNodeCreate(key="VS", name="VS-Mittel", gremiumId=g.id))
    assert out.path_key == "VS" and out.gremium_id == g.id
    assert sess.committed == 1


async def test_create_child_inherits_gremium_and_path() -> None:
    g = uuid.uuid4()
    parent = _budget(path_key="VS", gremium_id=g)
    sess = fake_session(result(parent), result())  # parent found, no sibling
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
    # A new cut-off date on the top budget re-derives start and end of every fiscal year.
    top = _budget(path_key="VS", fiscal_start_month=1, fiscal_start_day=1)
    fy = _fy(budget_id=top.id, year=2026)
    sess = fake_session(result(top), result(fy))  # _get_node, _fiscal_years_of
    svc = BudgetTreeService(sess)
    out = await svc.update_node(top.id, BudgetNodeUpdate(fiscalStartMonth=7, fiscalStartDay=1))
    assert out.fiscal_start_month == 7 and out.fiscal_start_day == 1
    assert fy.start_date == date(2026, 7, 1) and fy.end_date == date(2027, 6, 30)


async def test_update_node_stichtag_unchanged_skips_rederive() -> None:
    # The same cut-off value skips the fiscal year re-derive. Only the name changes.
    top = _budget(path_key="VS", fiscal_start_month=1, fiscal_start_day=1)
    sess = fake_session(result(top))  # only _get_node
    svc = BudgetTreeService(sess)
    out = await svc.update_node(top.id, BudgetNodeUpdate(name="Neu", fiscalStartMonth=1))
    assert out.name == "Neu" and out.fiscal_start_month == 1


async def test_delete_node_ok() -> None:
    # The queue holds the node, no child, no booking and no assigned application. Any
    # allocation cascades away with the node, so the delete proceeds.
    node = _budget()
    sess = fake_session(result(node), result(), result(), result())
    svc = BudgetTreeService(sess)
    await svc.delete_node(node.id)
    assert sess.deleted == [node]


async def test_delete_node_with_children() -> None:
    node = _budget()
    sess = fake_session(result(node), result(uuid.uuid4()))  # has child
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError):
        await svc.delete_node(node.id)


async def test_delete_node_with_bookings() -> None:
    # A childless centre that carries bookings must not be silently cascade-wiped.
    node = _budget()
    sess = fake_session(result(node), result(), result(uuid.uuid4()))  # no child, has booking
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError):
        await svc.delete_node(node.id)


async def test_delete_node_with_assigned_applications() -> None:
    # An application still assigned to the centre would be orphaned → block.
    node = _budget()
    # node, no child, no booking, has assigned application
    sess = fake_session(result(node), result(), result(), result(uuid.uuid4()))
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError):
        await svc.delete_node(node.id)


async def test_delete_node_with_allocation_only_succeeds() -> None:
    # Regression: a leaf that only has an allocation row (planning figure, no
    # children/bookings/apps) is now deletable — the old guard wrongly blocked it.
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
    """#budget-scope: a node below the top level resolves to its top-level ancestor.

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
    top = _budget(path_key="VS")
    sess = fake_session(result(top), result())  # top-level, no existing fys
    svc = BudgetTreeService(sess)
    out = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    assert out.year == 2026 and out.display == "2026"
    assert out.start_date == date(2026, 1, 1) and out.end_date == date(2026, 12, 31)
    assert sess.committed == 1


async def test_create_fiscal_year_offset_stichtag_display() -> None:
    # A cut-off date of 01.07. gives the period 01.07.2026 to 30.06.2027 and the label
    # '2026/27'.
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
    top = _budget(path_key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    # The queue holds _require_top_level and _get_fiscal_year. The year does not change,
    # so _fiscal_years_of does not run.
    sess = fake_session(result(top), result(fy))
    svc = BudgetTreeService(sess)
    out = await svc.update_fiscal_year(top.id, fy.id, FiscalYearUpdate(active=False))
    assert out.active is False and out.year == 2026


async def test_update_fiscal_year_change_year_rederives_dates() -> None:
    top = _budget(path_key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, year=2026)
    # _require_top_level, _get_fiscal_year, _fiscal_years_of (year changed → uniqueness check).
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
    node = _budget(path_key="VS")
    top = node
    fy = _fy(budget_id=uuid.uuid4())  # belongs to another top budget
    sess = fake_session(result(node), result(fy), result(top))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(node.id, fy.id, AllocationSet(allocated=Decimal("100")))


async def test_set_allocation_top_level_new() -> None:
    top = _budget(path_key="VS")
    fy = _fy(budget_id=top.id)
    # node, fy, top, _lock(self), own_children(none), self_alloc(none→create)
    sess = fake_session(result(top), result(fy), result(top), result(), result(), result())
    svc = BudgetTreeService(sess)
    out = await svc.set_allocation(top.id, fy.id, AllocationSet(allocated=Decimal("1000")))
    assert out.allocated == Decimal("1000") and sess.committed == 1


async def test_set_allocation_child_exceeds_parent() -> None:
    parent = _budget(path_key="VS")
    child = _budget(parent_id=parent.id, path_key="VS-800", key="800")
    top = parent
    fy = _fy(budget_id=top.id)
    sibling_rows = result((uuid.uuid4(), Decimal("600")))  # other children hold 600
    parent_alloc = _alloc(budget_id=parent.id, fy_id=fy.id, allocated="1000")
    # node, fy, top, _lock(self), _lock(parent), siblings, parent_alloc
    # → 600+500=1100>1000 → exceeds
    sess = fake_session(
        result(child), result(fy), result(top), result(), result(),
        sibling_rows, result(parent_alloc),
    )
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(child.id, fy.id, AllocationSet(allocated=Decimal("500")))


async def test_set_allocation_child_ok_update_existing() -> None:
    parent = _budget(path_key="VS")
    child = _budget(parent_id=parent.id, path_key="VS-800", key="800")
    top = parent
    fy = _fy(budget_id=top.id)
    sibling_rows = result((uuid.uuid4(), Decimal("100")))
    parent_alloc = _alloc(budget_id=parent.id, fy_id=fy.id, allocated="1000")
    own_children = result()  # leaf, no own children
    self_alloc = _alloc(budget_id=child.id, fy_id=fy.id, allocated="200")
    # node, fy, top, _lock(self), _lock(parent), siblings, parent_alloc, own_children, self_alloc
    sess = fake_session(
        result(child), result(fy), result(top), result(), result(), sibling_rows,
        result(parent_alloc), own_children, result(self_alloc),
    )
    svc = BudgetTreeService(sess)
    out = await svc.set_allocation(child.id, fy.id, AllocationSet(allocated=Decimal("300")))
    assert out.allocated == Decimal("300")
    assert self_alloc.allocated == Decimal("300")  # the service updates the existing row


async def test_set_allocation_below_children() -> None:
    top = _budget(path_key="VS")
    fy = _fy(budget_id=top.id)
    own_children = result((uuid.uuid4(), Decimal("700")))  # 700 already distributed
    # node, fy, top, _lock(self), own_children
    sess = fake_session(result(top), result(fy), result(top), result(), own_children)
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(top.id, fy.id, AllocationSet(allocated=Decimal("500")))


async def test_set_allocation_fy_not_found() -> None:
    node = _budget(path_key="VS")
    sess = fake_session(result(node), result())  # node found, fy None
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.set_allocation(node.id, uuid.uuid4(), AllocationSet(allocated=Decimal("1")))


async def test_set_allocation_top_not_found() -> None:
    node = _budget(path_key="VS")
    fy = _fy(budget_id=node.id)
    sess = fake_session(result(node), result(fy), result())  # top-level lookup → None
    svc = BudgetTreeService(sess)
    with pytest.raises(NotFoundError):
        await svc.set_allocation(node.id, fy.id, AllocationSet(allocated=Decimal("1")))


async def test_children_alloc_sum_excludes_self() -> None:
    # The sibling sum ignores the row of the node itself. This covers the exclude_id branch.
    parent = _budget(path_key="VS")
    child = _budget(parent_id=parent.id, path_key="VS-800", key="800")
    top = parent
    fy = _fy(budget_id=top.id)
    sibling_rows = result((child.id, Decimal("999")), (uuid.uuid4(), Decimal("100")))
    parent_alloc = _alloc(budget_id=parent.id, fy_id=fy.id, allocated="1000")
    # node, fy, top, _lock(self), _lock(parent), siblings, parent_alloc, own_children, self_alloc
    sess = fake_session(
        result(child), result(fy), result(top), result(), result(), sibling_rows,
        result(parent_alloc), result(), result(),
    )
    svc = BudgetTreeService(sess)
    out = await svc.set_allocation(child.id, fy.id, AllocationSet(allocated=Decimal("300")))
    # Only 100 from the siblings plus 300 gives 400, which stays under 1000. The service
    # skips the 999 row of the node.
    assert out.allocated == Decimal("300")


async def test_set_allocation_child_no_parent_alloc() -> None:
    parent = _budget(path_key="VS")
    child = _budget(parent_id=parent.id, path_key="VS-800", key="800")
    top = parent
    fy = _fy(budget_id=top.id)
    sibling_rows = result()  # no other children
    # node, fy, top, _lock(self), _lock(parent), siblings, parent_alloc(None)
    # → exceeds (0+1 > 0) → 422
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
    top = _budget(path_key="VS")
    node = top
    fy = _fy(budget_id=top.id, active=True)
    app = _app()
    # app, node, top, fiscal_years
    sess = fake_session(result(app), result(node), result(top), result(fy))
    svc = BudgetTreeService(sess)
    out = await svc.assign_budget(app.id, AssignBudgetRequest(budgetId=node.id))
    assert out.budget_id == node.id and out.fiscal_year_id == fy.id


async def test_assign_budget_app_not_found() -> None:
    svc = BudgetTreeService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc.assign_budget(uuid.uuid4(), AssignBudgetRequest(budgetId=uuid.uuid4()))


async def test_assign_budget_explicit_fiscal_year() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, active=True)
    app = _app()
    # _get_application, _get_node, _top_level, _get_fiscal_year
    sess = fake_session(result(app), result(node), result(top), result(fy))
    svc = BudgetTreeService(sess)
    out = await svc.assign_budget(
        app.id, AssignBudgetRequest(budgetId=node.id, fiscalYearId=fy.id)
    )
    assert out.budget_id == node.id and out.fiscal_year_id == fy.id


async def test_assign_budget_ambiguous_requires_fiscal_year() -> None:
    # Two or more active fiscal years without an explicit fiscalYearId give 422 instead of
    # a silent NULL (R7.1e).
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy1 = _fy(id=uuid.uuid4(), budget_id=top.id)
    fy2 = _fy(id=uuid.uuid4(), budget_id=top.id)
    app = _app()
    # _get_application, _get_node, _top_level, _fiscal_years_of
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
    top = _budget(path_key="VS")
    node = top
    fy = _fy(budget_id=uuid.uuid4())  # another top budget
    app = _app(budget_id=node.id)
    sess = fake_session(result(app), result(node), result(top), result(fy))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.move_fiscal_year(app.id, MoveFiscalYearRequest(fiscalYearId=fy.id))


async def test_get_tree_assembles() -> None:
    g = uuid.uuid4()
    fy_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", gremium_id=g, key="VS")
    top.accepted_state_keys = ["approved"]  # accepted states count as bound
    top.denied_state_keys = ["rejected"]
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    sess = fake_session(
        result(top),                                            # nodes
        result(alloc),                                          # allocations
        result(  # app rows (id, path, fy, amount, state)
            (uuid.uuid4(), "VS", fy_id, Decimal("250"), "approved"),    # → bound
            (uuid.uuid4(), "VS", fy_id, Decimal("120"), "submitted"),   # → requested (in-flight)
            (uuid.uuid4(), "VS", fy_id, Decimal("999"), "rejected"),    # → excluded
        ),
        result(),                                               # expense rows (none)
    )
    svc = BudgetTreeService(sess)
    tree = await svc.get_tree()
    assert len(tree) == 1
    view = tree[0].by_fiscal_year[0]
    assert view.allocated == Decimal("1000")
    assert view.bound == Decimal("250")        # only 'approved'
    assert view.expended == Decimal("0")
    assert view.committed == Decimal("250")    # bound + expended
    assert view.requested == Decimal("120")    # 'submitted', not 'rejected'
    assert view.available == Decimal("750")


async def test_get_tree_rolls_up_standalone_expenses() -> None:
    """Standalone expenses count as expended, not as bound."""
    g = uuid.uuid4()
    fy_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", gremium_id=g, key="VS")
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    sess = fake_session(
        result(top),                            # nodes
        result(alloc),                          # allocations
        result(),                               # application rows (none)
        result(("VS", fy_id, Decimal("60"), "expense", None)),  # standalone expense (#25)
    )
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.bound == Decimal("0")
    assert view.expended == Decimal("60")
    assert view.committed == Decimal("60")     # bound + expended
    assert view.available == Decimal("940")


async def test_get_tree_income_increases_available() -> None:
    """Income raises the available budget."""
    fy_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    sess = fake_session(
        result(top),
        result(alloc),
        result(),                               # application rows (none)
        result(("VS", fy_id, Decimal("200"), "income", None)),  # income booking
    )
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.income == Decimal("200")
    assert view.expended == Decimal("0")
    assert view.available == Decimal("1200")   # 1000 − 0 − 0 + 200


async def test_get_tree_linked_expense_replaces_bound() -> None:
    """An expense linked to an application replaces that binding in proportion."""
    fy_id = uuid.uuid4()
    app_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    top.accepted_state_keys = ["approved"]
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    sess = fake_session(
        result(top),
        result(alloc),
        result((app_id, "VS", fy_id, Decimal("250"), "approved")),   # approved app
        result(("VS", fy_id, Decimal("100"), "expense", app_id)),    # 100 spent on it
    )
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.bound == Decimal("150")        # 250 − 100 stays bound
    assert view.expended == Decimal("100")
    assert view.committed == Decimal("250")    # bound + expended = the original binding
    assert view.available == Decimal("750")    # 1000 − 150 − 100


async def test_resolve_fiscal_year_explicit_ok() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
    sess = fake_session(result(top), result(fy))  # _top_level, _get_fiscal_year
    svc = BudgetTreeService(sess)
    assert await svc._resolve_fiscal_year(node, fy.id) == fy.id


async def test_resolve_fiscal_year_wrong_top() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy = _fy(id=uuid.uuid4(), budget_id=uuid.uuid4())  # belongs to another top budget
    sess = fake_session(result(top), result(fy))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc._resolve_fiscal_year(node, fy.id)


async def test_resolve_fiscal_year_ambiguous() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy1 = _fy(id=uuid.uuid4(), budget_id=top.id)
    fy2 = _fy(id=uuid.uuid4(), budget_id=top.id)
    sess = fake_session(result(top), result(fy1, fy2))  # _top_level, _fiscal_years_of
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc._resolve_fiscal_year(node, None)


async def test_delete_expense_not_found() -> None:
    svc = BudgetTreeService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc.delete_expense(uuid.uuid4())


def test_expense_out_maps_metadata_fields() -> None:
    """#1-1, #1-2, #3 and #4: the extra metadata reaches the output DTO in camelCase."""
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
