"""TDD: BudgetTreeService (CR #76/#78) ohne DB — Fake-Session deckt jeden Branch (100 %).

Die Reihenfolge der ``execute``-Ergebnisse spiegelt den Service-Ablauf (FIFO-Queue
je ``execute``, s. ``tests/auth_fakes.FakeSession``).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.admin.models import Gremium
from app.modules.applications.models import Application
from app.modules.budget.tree_models import Budget, BudgetAllocation, FiscalYear
from app.modules.budget.tree_schemas import (
    AllocationSet,
    AssignBudgetRequest,
    BudgetNodeCreate,
    BudgetNodeUpdate,
    FiscalYearCreate,
    FiscalYearUpdate,
    MoveFiscalYearRequest,
)
from app.modules.budget.tree_service import BudgetTreeService
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from tests.auth_fakes import fake_session, result


def _budget(*, id=None, parent_id=None, path_key="VS", gremium_id=None, key="VS", name="N"):  # noqa: ANN001
    b = Budget(
        parent_id=parent_id, gremium_id=gremium_id, key=key,
        path_key=path_key, name=name, currency="EUR", active=True,
    )
    b.id = id or uuid.uuid4()
    return b


def _fy(  # noqa: ANN001
    *, id=None, budget_id=None, start=date(2026, 1, 1), end=date(2026, 12, 31),
    active=True, label="HHJ",
):
    f = FiscalYear(budget_id=budget_id, label=label, start_date=start, end_date=end, active=active)
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


# ------------------------------------------------------------------ create_node
async def test_create_node_invalid_key() -> None:
    svc = BudgetTreeService(fake_session())
    with pytest.raises(ValidationProblem):
        await svc.create_node(BudgetNodeCreate(key="VS-800", name="x"))


async def test_create_top_level_without_gremium_ok() -> None:
    # #22: Budgets sind nicht an ein Gremium gebunden — Top-Level ohne gremiumId ok.
    sess = fake_session(result())  # nur Sibling-Check (kein Gremium-Lookup)
    svc = BudgetTreeService(sess)
    out = await svc.create_node(BudgetNodeCreate(key="VS", name="VS-Mittel"))
    assert out.path_key == "VS" and out.gremium_id is None


async def test_create_top_level_gremium_not_found() -> None:
    svc = BudgetTreeService(fake_session(result()))  # gremium lookup → None
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


# ------------------------------------------------------------------ update/delete
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


async def test_delete_node_ok() -> None:
    node = _budget()
    sess = fake_session(result(node), result(), result())  # node, no child, no alloc
    svc = BudgetTreeService(sess)
    await svc.delete_node(node.id)
    assert sess.deleted == [node]


async def test_delete_node_with_children() -> None:
    node = _budget()
    sess = fake_session(result(node), result(uuid.uuid4()))  # has child
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError):
        await svc.delete_node(node.id)


async def test_delete_node_with_allocations() -> None:
    node = _budget()
    sess = fake_session(result(node), result(), result(uuid.uuid4()))  # no child, has alloc
    svc = BudgetTreeService(sess)
    with pytest.raises(ConflictError):
        await svc.delete_node(node.id)


async def test_delete_node_not_found() -> None:
    svc = BudgetTreeService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc.delete_node(uuid.uuid4())


# ------------------------------------------------------------------ fiscal years
async def test_list_fiscal_years_not_top_level() -> None:
    child = _budget(parent_id=uuid.uuid4(), path_key="VS-800")
    svc = BudgetTreeService(fake_session(result(child)))
    with pytest.raises(ValidationProblem):
        await svc.list_fiscal_years(child.id)


async def test_list_fiscal_years_ok() -> None:
    top = _budget(path_key="VS")
    fy = _fy(budget_id=top.id)
    sess = fake_session(result(top), result(fy))
    svc = BudgetTreeService(sess)
    out = await svc.list_fiscal_years(top.id)
    assert len(out) == 1 and out[0].budget_id == top.id


async def test_create_fiscal_year_ok() -> None:
    top = _budget(path_key="VS")
    sess = fake_session(result(top), result())  # top-level, no existing fys
    svc = BudgetTreeService(sess)
    out = await svc.create_fiscal_year(
        top.id,
        FiscalYearCreate(label="HHJ 2026", startDate=date(2026, 4, 1), endDate=date(2027, 3, 31)),
    )
    assert out.label == "HHJ 2026"
    assert sess.committed == 1


async def test_create_fiscal_year_bad_dates() -> None:
    top = _budget(path_key="VS")
    svc = BudgetTreeService(fake_session(result(top)))
    with pytest.raises(ValidationProblem):
        await svc.create_fiscal_year(
            top.id,
            FiscalYearCreate(label="x", startDate=date(2026, 5, 1), endDate=date(2026, 5, 1)),
        )


async def test_create_fiscal_year_overlap() -> None:
    top = _budget(path_key="VS")
    existing = _fy(budget_id=top.id, start=date(2026, 1, 1), end=date(2026, 12, 31))
    sess = fake_session(result(top), result(existing))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.create_fiscal_year(
            top.id,
            FiscalYearCreate(label="y", startDate=date(2026, 6, 1), endDate=date(2027, 6, 1)),
        )


async def test_update_fiscal_year_ok_defaults() -> None:
    top = _budget(path_key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
    # _require_top_level(top), _get_fiscal_year(fy), _fiscal_years_of (only itself → filtered out)
    sess = fake_session(result(top), result(fy), result(fy))
    svc = BudgetTreeService(sess)
    out = await svc.update_fiscal_year(top.id, fy.id, FiscalYearUpdate(label="HHJ neu"))
    assert out.label == "HHJ neu"


async def test_update_fiscal_year_bad_dates() -> None:
    top = _budget(path_key="VS")
    fy = _fy(budget_id=top.id)
    sess = fake_session(result(top), result(fy))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.update_fiscal_year(
            top.id, fy.id, FiscalYearUpdate(startDate=date(2026, 5, 1), endDate=date(2026, 4, 1))
        )


async def test_update_fiscal_year_overlap_with_other() -> None:
    top = _budget(path_key="VS")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id, start=date(2026, 1, 1), end=date(2026, 6, 30))
    other = _fy(id=uuid.uuid4(), budget_id=top.id, start=date(2026, 7, 1), end=date(2026, 12, 31))
    sess = fake_session(result(top), result(fy), result(fy, other))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.update_fiscal_year(
            top.id, fy.id, FiscalYearUpdate(endDate=date(2026, 8, 1))  # ragt in 'other'
        )


# ------------------------------------------------------------------ allocation
async def test_set_allocation_fy_mismatch() -> None:
    node = _budget(path_key="VS")
    top = node
    fy = _fy(budget_id=uuid.uuid4())  # gehört zu fremdem Top-Budget
    sess = fake_session(result(node), result(fy), result(top))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(node.id, fy.id, AllocationSet(allocated=Decimal("100")))


async def test_set_allocation_top_level_new() -> None:
    top = _budget(path_key="VS")
    fy = _fy(budget_id=top.id)
    # node, fy, top, own_children(none), self_alloc(none→create)
    sess = fake_session(result(top), result(fy), result(top), result(), result())
    svc = BudgetTreeService(sess)
    out = await svc.set_allocation(top.id, fy.id, AllocationSet(allocated=Decimal("1000")))
    assert out.allocated == Decimal("1000") and sess.committed == 1


async def test_set_allocation_child_exceeds_parent() -> None:
    parent = _budget(path_key="VS")
    child = _budget(parent_id=parent.id, path_key="VS-800", key="800")
    top = parent
    fy = _fy(budget_id=top.id)
    sibling_rows = result((uuid.uuid4(), Decimal("600")))  # andere Kinder = 600
    parent_alloc = _alloc(budget_id=parent.id, fy_id=fy.id, allocated="1000")
    # node, fy, top, siblings, parent_alloc → 600+500>... wait 600+500=1100>1000 → exceeds
    sess = fake_session(result(child), result(fy), result(top), sibling_rows, result(parent_alloc))
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
    sess = fake_session(
        result(child), result(fy), result(top), sibling_rows,
        result(parent_alloc), own_children, result(self_alloc),
    )
    svc = BudgetTreeService(sess)
    out = await svc.set_allocation(child.id, fy.id, AllocationSet(allocated=Decimal("300")))
    assert out.allocated == Decimal("300")
    assert self_alloc.allocated == Decimal("300")  # bestehende Zeile aktualisiert


async def test_set_allocation_below_children() -> None:
    top = _budget(path_key="VS")
    fy = _fy(budget_id=top.id)
    own_children = result((uuid.uuid4(), Decimal("700")))  # bereits 700 verteilt
    sess = fake_session(result(top), result(fy), result(top), own_children)
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
    # Geschwister-Summe ignoriert die Zeile des Knotens selbst (exclude_id-Zweig).
    parent = _budget(path_key="VS")
    child = _budget(parent_id=parent.id, path_key="VS-800", key="800")
    top = parent
    fy = _fy(budget_id=top.id)
    sibling_rows = result((child.id, Decimal("999")), (uuid.uuid4(), Decimal("100")))
    parent_alloc = _alloc(budget_id=parent.id, fy_id=fy.id, allocated="1000")
    sess = fake_session(
        result(child), result(fy), result(top), sibling_rows,
        result(parent_alloc), result(), result(),
    )
    svc = BudgetTreeService(sess)
    out = await svc.set_allocation(child.id, fy.id, AllocationSet(allocated=Decimal("300")))
    # nur 100 (Geschwister) + 300 = 400 ≤ 1000; die 999-Zeile des Knotens wird übersprungen.
    assert out.allocated == Decimal("300")


async def test_set_allocation_child_no_parent_alloc() -> None:
    parent = _budget(path_key="VS")
    child = _budget(parent_id=parent.id, path_key="VS-800", key="800")
    top = parent
    fy = _fy(budget_id=top.id)
    sibling_rows = result()  # keine anderen Kinder
    # parent_alloc None → exceeds (0+1 > 0) → 422
    sess = fake_session(result(child), result(fy), result(top), sibling_rows, result())
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(child.id, fy.id, AllocationSet(allocated=Decimal("1")))


# ------------------------------------------------------------------ assignment
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
    fy = _fy(budget_id=uuid.uuid4())  # fremdes Top-Budget
    app = _app(budget_id=node.id)
    sess = fake_session(result(app), result(node), result(top), result(fy))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc.move_fiscal_year(app.id, MoveFiscalYearRequest(fiscalYearId=fy.id))


# ------------------------------------------------------------------ tree view
async def test_get_tree_assembles() -> None:
    g = uuid.uuid4()
    fy_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", gremium_id=g, key="VS")
    top.accepted_state_keys = ["approved"]  # angenommene States → gebunden
    top.denied_state_keys = ["rejected"]
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    sess = fake_session(
        result(top),                                            # nodes
        result(alloc),                                          # allocations
        result(                                                 # app rows (path, fy, amount, state)
            ("VS", fy_id, Decimal("250"), "approved"),          # → committed
            ("VS", fy_id, Decimal("120"), "submitted"),         # → requested (in-flight)
            ("VS", fy_id, Decimal("999"), "rejected"),          # → excluded
        ),
        result(),                                               # expense rows (none)
    )
    svc = BudgetTreeService(sess)
    tree = await svc.get_tree()
    assert len(tree) == 1
    view = tree[0].by_fiscal_year[0]
    assert view.allocated == Decimal("1000")
    assert view.committed == Decimal("250")    # nur 'approved'
    assert view.requested == Decimal("120")    # 'submitted', nicht 'rejected'
    assert view.available == Decimal("750")


# ------------------------------------------------------------------- expenses
async def test_get_tree_rolls_up_standalone_expenses() -> None:
    """Eigenständige Ausgaben (#25) zählen wie Anträge als gebundener Verbrauch."""
    g = uuid.uuid4()
    fy_id = uuid.uuid4()
    top = _budget(id=uuid.uuid4(), path_key="VS", gremium_id=g, key="VS")
    alloc = _alloc(budget_id=top.id, fy_id=fy_id, allocated="1000")
    sess = fake_session(
        result(top),                            # nodes
        result(alloc),                          # allocations
        result(),                               # committed application rows (none)
        result(("VS", fy_id, Decimal("60"))),   # standalone expense rows (#25)
    )
    svc = BudgetTreeService(sess)
    view = (await svc.get_tree())[0].by_fiscal_year[0]
    assert view.committed == Decimal("60")
    assert view.available == Decimal("940")


async def test_resolve_expense_fiscal_year_explicit_ok() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy = _fy(id=uuid.uuid4(), budget_id=top.id)
    sess = fake_session(result(top), result(fy))  # _top_level, _get_fiscal_year
    svc = BudgetTreeService(sess)
    assert await svc._resolve_expense_fiscal_year(node, fy.id) == fy.id


async def test_resolve_expense_fiscal_year_wrong_top() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy = _fy(id=uuid.uuid4(), budget_id=uuid.uuid4())  # gehört zu anderem Top-Budget
    sess = fake_session(result(top), result(fy))
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc._resolve_expense_fiscal_year(node, fy.id)


async def test_resolve_expense_fiscal_year_ambiguous() -> None:
    top = _budget(id=uuid.uuid4(), path_key="VS", key="VS")
    node = _budget(id=uuid.uuid4(), path_key="VS-800", key="800")
    fy1 = _fy(id=uuid.uuid4(), budget_id=top.id)
    fy2 = _fy(id=uuid.uuid4(), budget_id=top.id)
    sess = fake_session(result(top), result(fy1, fy2))  # _top_level, _fiscal_years_of
    svc = BudgetTreeService(sess)
    with pytest.raises(ValidationProblem):
        await svc._resolve_expense_fiscal_year(node, None)


async def test_delete_expense_not_found() -> None:
    svc = BudgetTreeService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc.delete_expense(uuid.uuid4())
