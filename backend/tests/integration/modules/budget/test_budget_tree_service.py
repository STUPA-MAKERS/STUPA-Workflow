"""Integration (real Postgres, testcontainers): the budget tree end to end (CR #76/#78).

The tests prove the three critical constraints against a real schema (data-model
§1/§5.8). The product owner named them in testing.md.

* **Path composition** and UNIQUE(parent,key). The tree builds top, then child, then
  `VS-800`.
* **Fiscal-year disjointness** (R7.1f/g). An overlapping fiscal year gives 422.
* **Top-down allocation** (R7.1b). The sum of the children must stay at or below the
  parent, otherwise 422.
* **Roll-up correctness** (R7.1c). The committed amount of an approved application rolls
  up from the cost center to the root. The roll-up follows the `path_key` prefix.
* A delete with children gives 409.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_models import Budget, BudgetAllocation, BudgetExpense
from app.modules.budget.tree_schemas import (
    AllocationSet,
    BudgetNodeCreate,
    BudgetNodeUpdate,
    ExpenseCreate,
    ExpenseUpdate,
    FiscalYearCreate,
    InvoiceCreate,
    TransferCreate,
)
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.models import FormVersion
from app.shared.errors import ConflictError, ValidationProblem

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _gremium(session: AsyncSession) -> Gremium:
    g = Gremium(name="FS Informatik", slug=f"fs-{uuid.uuid4().hex[:8]}")
    session.add(g)
    await session.commit()
    return g


def _suffix() -> str:
    """Return a unique alphanumeric key suffix.

    The tests do not clear the tables.
    """
    return uuid.uuid4().hex[:6]


async def test_path_composition_and_tree(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top_key = f"VS{_suffix()}"
    top = await svc.create_node(BudgetNodeCreate(key=top_key, name="VS-Mittel", gremiumId=g.id))
    child = await svc.create_node(BudgetNodeCreate(key="800", name="Dezentral", parentId=top.id))
    assert top.path_key == top_key
    assert child.path_key == f"{top_key}-800"
    assert child.gremium_id == g.id  # the child inherits the Gremium

    tree = await svc.get_tree(gremium_id=g.id)
    roots = [n for n in tree if n.id == top.id]
    assert roots and roots[0].children[0].id == child.id


async def test_fiscal_year_unique_year(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(
        BudgetNodeCreate(
            key=f"HJ{_suffix()}",
            name="Top",
            gremiumId=g.id,
            fiscalStartMonth=7,
            fiscalStartDay=1,
        )
    )
    fy26 = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    # A start day of July 1 shifts the fiscal year: display '2026/27', Jul 1 to Jun 30.
    assert fy26.display == "2026/27"
    assert fy26.start_date == date(2026, 7, 1) and fy26.end_date == date(2027, 6, 30)
    await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2027))
    # The same year again gives 422. A year is unique per top budget.
    with pytest.raises(ValidationProblem):
        await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))


async def test_top_down_allocation_constraint(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"AL{_suffix()}", name="Top", gremiumId=g.id))
    c1 = await svc.create_node(BudgetNodeCreate(key="01", name="K1", parentId=top.id))
    c2 = await svc.create_node(BudgetNodeCreate(key="02", name="K2", parentId=top.id))
    fy = await svc.create_fiscal_year(
        top.id,
        FiscalYearCreate(year=2026),
    )
    await svc.set_allocation(top.id, fy.id, AllocationSet(allocated=Decimal("1000")))
    await svc.set_allocation(c1.id, fy.id, AllocationSet(allocated=Decimal("600")))
    # 600 + 500 = 1100 is above 1000, so 422.
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(c2.id, fy.id, AllocationSet(allocated=Decimal("500")))
    # 600 + 400 = 1000 is at the cap, so it passes.
    await svc.set_allocation(c2.id, fy.id, AllocationSet(allocated=Decimal("400")))
    # Lowering the parent below the sum of the children gives 422.
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(top.id, fy.id, AllocationSet(allocated=Decimal("900")))


async def test_rename_key_recomputes_descendant_paths(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"RK{_suffix()}", name="Top", gremiumId=g.id))
    mid = await svc.create_node(BudgetNodeCreate(key="800", name="Mid", parentId=top.id))
    leaf = await svc.create_node(BudgetNodeCreate(key="04", name="Leaf", parentId=mid.id))
    assert leaf.path_key == f"{top.path_key}-800-04"

    # Rename mid from 800 to 810. The path of mid and of leaf follows.
    out = await svc.update_node(mid.id, BudgetNodeUpdate(key="810", name="Mid"))
    assert out.path_key == f"{top.path_key}-810"
    leaf_row = await session.get(Budget, leaf.id)
    assert leaf_row is not None and leaf_row.path_key == f"{top.path_key}-810-04"

    # Conflict: the same key as a sibling gives 409.
    await svc.create_node(BudgetNodeCreate(key="900", name="Sib", parentId=top.id))
    with pytest.raises(ConflictError):
        await svc.update_node(mid.id, BudgetNodeUpdate(key="900"))


async def test_transfer(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"TR{_suffix()}", name="Top", gremiumId=g.id))
    a = await svc.create_node(BudgetNodeCreate(key="01", name="A", parentId=top.id))
    b = await svc.create_node(BudgetNodeCreate(key="02", name="B", parentId=top.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))

    # A transfer of 200 from A to B books an expense on A and an income on B, same
    # fiscal year.
    transfer = await svc.create_transfer(
        TransferCreate(
            fromBudgetId=a.id,
            toBudgetId=b.id,
            fiscalYearId=fy.id,
            amount=Decimal("200"),
            description="Umbuchung",
        ),
        actor="tester",
    )
    page = await svc.list_expenses_paged(budget_id=top.id, fiscal_year_id=fy.id)
    by_transfer = [e for e in page.items if e.transfer_id == transfer.transfer_id]
    assert {e.kind for e in by_transfer} == {"expense", "income"}
    assert all(e.amount == Decimal("200") for e in by_transfer)

    # A delete of one side removes both transfer bookings.
    await svc.delete_expense(transfer.expense_id)
    page = await svc.list_expenses_paged(budget_id=top.id, fiscal_year_id=fy.id)
    assert not [e for e in page.items if e.transfer_id == transfer.transfer_id]


async def test_transfer_leg_amount_is_readonly(session: AsyncSession) -> None:
    """A single leg cannot move on its own, or the pair drifts apart."""
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"TL{_suffix()}", name="Top", gremiumId=g.id))
    a = await svc.create_node(BudgetNodeCreate(key="01", name="A", parentId=top.id))
    b = await svc.create_node(BudgetNodeCreate(key="02", name="B", parentId=top.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    transfer = await svc.create_transfer(
        TransferCreate(
            fromBudgetId=a.id, toBudgetId=b.id, fiscalYearId=fy.id,
            amount=Decimal("100"), description="Umbuchung",
        ),
        actor="tester",
    )

    with pytest.raises(ConflictError) as ei:
        await svc.update_expense(transfer.expense_id, ExpenseUpdate(amount=Decimal("500")))
    assert ei.value.code == "transfer_leg_readonly"

    with pytest.raises(ConflictError):
        await svc.update_expense(transfer.expense_id, ExpenseUpdate(budgetId=b.id))

    leg = await session.get(BudgetExpense, transfer.expense_id)
    assert leg is not None and leg.amount == Decimal("100") and leg.budget_id == a.id


async def test_list_transfers_total_matches_reachable_rows(session: AsyncSession) -> None:
    """A source leg without its income row drops out of the rows and out of `total`."""
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"TC{_suffix()}", name="Top", gremiumId=g.id))
    a = await svc.create_node(BudgetNodeCreate(key="01", name="A", parentId=top.id))
    b = await svc.create_node(BudgetNodeCreate(key="02", name="B", parentId=top.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    transfer = await svc.create_transfer(
        TransferCreate(
            fromBudgetId=a.id, toBudgetId=b.id, fiscalYearId=fy.id,
            amount=Decimal("100"), description="Umbuchung",
        ),
        actor="tester",
    )
    page = await svc.list_transfers_paged(transfer_id=transfer.transfer_id)
    assert page.total == 1 and len(page.items) == 1

    income = await session.get(BudgetExpense, transfer.income_id)
    assert income is not None
    await session.delete(income)
    await session.commit()

    page = await svc.list_transfers_paged(transfer_id=transfer.transfer_id)
    assert page.total == 0 and page.items == []


async def test_delete_allocation_unblocks_fiscal_year_delete(session: AsyncSession) -> None:
    """An allocated fiscal year stays deletable: drop the allocation, then the year."""
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"DQ{_suffix()}", name="Top", gremiumId=g.id))
    child = await svc.create_node(BudgetNodeCreate(key="01", name="K", parentId=top.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    await svc.set_allocation(top.id, fy.id, AllocationSet(allocated=Decimal("1000")))
    await svc.set_allocation(child.id, fy.id, AllocationSet(allocated=Decimal("400")))

    with pytest.raises(ConflictError) as ei:
        await svc.delete_fiscal_year(top.id, fy.id)
    assert ei.value.code == "fiscal_year_has_allocations"

    # The parent still covers 400 of children, so its allocation cannot go first.
    with pytest.raises(ValidationProblem):
        await svc.delete_allocation(top.id, fy.id)

    await svc.delete_allocation(child.id, fy.id)
    await svc.delete_allocation(top.id, fy.id)
    left = (
        await session.execute(
            select(BudgetAllocation.id).where(BudgetAllocation.fiscal_year_id == fy.id)
        )
    ).all()
    assert left == []

    await svc.delete_fiscal_year(top.id, fy.id)


async def test_expense_actor_resolved_to_display_name(session: AsyncSession) -> None:
    """The server resolves `actor` (the principal `sub`) to a display name.

    See #no-uuids-in-ui. `actorName` carries the display name and `actor` stays the raw
    UUID. An unknown actor, for example a legacy name, gives `actorName is None`.
    """
    from app.modules.auth.models import Principal as PrincipalRow

    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"AC{_suffix()}", name="Top", gremiumId=g.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))

    sub = str(uuid.uuid4())  # a UUID sub, the same shape the real IdP sends
    session.add(PrincipalRow(sub=sub, display_name="Erika Mustermann", email="e@x.de"))
    await session.commit()

    booked = await svc.book_expense(
        ExpenseCreate(budgetId=top.id, fiscalYearId=fy.id, amount=Decimal("5"), description="x"),
        actor=sub,
    )
    # The create response resolves the name at once.
    assert booked.actor == sub
    assert booked.actor_name == "Erika Mustermann"

    # An unknown actor, a legacy name without a principal, stays unresolved.
    legacy = await svc.book_expense(
        ExpenseCreate(budgetId=top.id, fiscalYearId=fy.id, amount=Decimal("7"), description="y"),
        actor="legacy-name",
    )
    assert legacy.actor == "legacy-name" and legacy.actor_name is None

    # The list path resolves the names too, as a batch.
    page = await svc.list_expenses_paged(budget_id=top.id, fiscal_year_id=fy.id)
    by_id = {e.id: e for e in page.items}
    assert by_id[booked.id].actor_name == "Erika Mustermann"
    assert by_id[legacy.id].actor_name is None


async def test_committed_rollup(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"RU{_suffix()}", name="Top", gremiumId=g.id))
    mid = await svc.create_node(BudgetNodeCreate(key="800", name="Mid", parentId=top.id))
    leaf = await svc.create_node(BudgetNodeCreate(key="04", name="Leaf", parentId=mid.id))
    fy = await svc.create_fiscal_year(
        top.id,
        FiscalYearCreate(year=2026),
    )

    # An application counts as approved when its flow state is in the accepted_state_keys
    # of the top budget.
    app_type = ApplicationType(key=f"t-{_suffix()}", name_i18n={})
    session.add(app_type)
    await session.flush()
    fv = FormVersion(application_type_id=app_type.id, version=1)
    flv = FlowVersion(version=1)
    session.add_all([fv, flv])
    await session.flush()
    state = State(flow_version_id=flv.id, key="approved", label_i18n={}, kind="normal")
    session.add(state)
    await session.flush()
    app = Application(
        type_id=app_type.id,
        form_version_id=fv.id,
        flow_version_id=flv.id,
        current_state_id=state.id,
        budget_id=leaf.id,
        fiscal_year_id=fy.id,
        amount=Decimal("250"),
    )
    session.add(app)
    # For this top budget, 'approved' counts as committed.
    top_row = await session.get(Budget, top.id)
    assert top_row is not None
    top_row.accepted_state_keys = ["approved"]
    await session.commit()

    tree = await svc.get_tree(gremium_id=g.id)
    top_node = next(n for n in tree if n.id == top.id)

    def committed(node) -> Decimal:  # noqa: ANN001
        return node.by_fiscal_year[0].committed if node.by_fiscal_year else Decimal("0")

    mid_node = top_node.children[0]
    leaf_node = mid_node.children[0]
    # The committed amount rolls up from leaf to mid to top, 250 at each level.
    assert committed(leaf_node) == Decimal("250")
    assert committed(mid_node) == Decimal("250")
    assert committed(top_node) == Decimal("250")


async def test_delete_with_children_conflicts(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"DL{_suffix()}", name="Top", gremiumId=g.id))
    await svc.create_node(BudgetNodeCreate(key="01", name="K", parentId=top.id))
    with pytest.raises(ConflictError):
        await svc.delete_node(top.id)


async def test_delete_leaf_with_allocation_succeeds(session: AsyncSession) -> None:
    """Regression: a childless cost center that only carries an allocation is deletable.

    The allocation is a planning figure. The old guard blocked any node with an
    allocation row. A reset of an allocation to 0 keeps the row, so such a leaf could
    never be deleted.
    """
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"DA{_suffix()}", name="Top", gremiumId=g.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    await svc.set_allocation(top.id, fy.id, AllocationSet(allocated=Decimal("500")))

    await svc.delete_node(top.id)  # no children, bookings or applications, so it deletes

    assert await session.get(Budget, top.id) is None  # the allocation cascades away


async def test_list_expenses_fuzzy_search(session: AsyncSession) -> None:
    """Fuzzy search (#3) against a real Postgres: pg_trgm filters and ranks bookings.

    This proves the real trigram path, not the ILIKE fallback. A typo in the query still
    finds the closest description. Other bookings drop out. The rank puts the hit first.
    """
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"FZ{_suffix()}", name="Top", gremiumId=g.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    for desc in ("Konferenzgebühr", "Druckerpapier", "Bahnticket Berlin"):
        await svc.book_expense(
            ExpenseCreate(
                budgetId=top.id,
                fiscalYearId=fy.id,
                amount=Decimal("10"),
                description=desc,
            ),
            actor="tester",
        )

    # The typo "Konferenzgebuehr" still hits, through trigram similarity.
    page = await svc.list_expenses_paged(
        budget_id=top.id, fiscal_year_id=fy.id, q="Konferenzgebuehr"
    )
    assert page.total == 1
    assert page.items[0].description == "Konferenzgebühr"

    # A unique substring gives exactly one booking. Other bookings drop out.
    only = await svc.list_expenses_paged(budget_id=top.id, fiscal_year_id=fy.id, q="Druckerpapier")
    assert [e.description for e in only.items] == ["Druckerpapier"]

    # No hit gives an empty page. Count and rows agree, so infinite scroll does not drift.
    empty = await svc.list_expenses_paged(budget_id=top.id, fiscal_year_id=fy.id, q="zzzzzznope")
    assert empty.total == 0 and empty.items == []


async def test_list_expenses_exact_id_filter(session: AsyncSession) -> None:
    """The `id` filter (#expenses-ux2) returns exactly one booking.

    The exact booking deeplink returns that one booking, even without any other
    filter.
    """
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(BudgetNodeCreate(key=f"ID{_suffix()}", name="Top", gremiumId=g.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    first = await svc.book_expense(
        ExpenseCreate(
            budgetId=top.id, fiscalYearId=fy.id, amount=Decimal("10"), description="Erste"
        ),
        actor="tester",
    )
    await svc.book_expense(
        ExpenseCreate(
            budgetId=top.id, fiscalYearId=fy.id, amount=Decimal("20"), description="Zweite"
        ),
        actor="tester",
    )

    page = await svc.list_expenses_paged(expense_id=first.id)
    assert page.total == 1
    assert [e.id for e in page.items] == [first.id]

    # An unknown UUID gives an empty page, not 404. The list stays a filter view.
    empty = await svc.list_expenses_paged(expense_id=uuid.uuid4())
    assert empty.total == 0 and empty.items == []


async def test_list_invoices_search_filter_pagination(session: AsyncSession) -> None:
    """Server-side invoice search (#invoices): fuzzy `q`, filters and offset paging.

    Against a real Postgres this proves the trigram path, so a typo still hits. It also
    proves the status, gross and date predicates that hang on the shared `filters`. The
    count query and the row query use the same predicates, so `total` and the hits do
    not drift. A SQLite stub would take the ILIKE substring fallback with rank 0.0,
    which keeps the same API green.
    """
    svc = BudgetTreeService(session)
    invoices = [
        InvoiceCreate(
            number="R-2026-001",
            supplier="Konferenzgebühr GmbH",
            grossAmount=Decimal("100"),
            status="open",
            issueDate=date(2026, 1, 10),
            dueDate=date(2026, 2, 10),
        ),
        InvoiceCreate(
            number="R-2026-002",
            supplier="Druckerei Müller",
            note="Druckerpapier A4",
            grossAmount=Decimal("250"),
            status="paid",
            issueDate=date(2026, 3, 5),
            dueDate=date(2026, 4, 5),
        ),
        InvoiceCreate(
            number="R-2026-003",
            supplier="Bahn AG",
            grossAmount=Decimal("500"),
            status="open",
            issueDate=date(2026, 6, 1),
            dueDate=date(2026, 7, 1),
        ),
    ]
    for payload in invoices:
        await svc.create_invoice(payload, actor="tester")

    # Fuzzy: the typo "Konferenzgebuehr" still hits the closest invoice.
    hit = await svc.list_invoices_paged(q="Konferenzgebuehr")
    assert hit.total == 1
    assert hit.items[0].supplier == "Konferenzgebühr GmbH"

    # Fuzzy over the note. Other invoices drop out.
    note_hit = await svc.list_invoices_paged(q="Druckerpapier")
    assert [i.number for i in note_hit.items] == ["R-2026-002"]

    open_only = await svc.list_invoices_paged(status="open")
    assert open_only.total == 2
    assert {i.status for i in open_only.items} == {"open"}

    mid = await svc.list_invoices_paged(gross_min=Decimal("200"), gross_max=Decimal("600"))
    assert {i.number for i in mid.items} == {"R-2026-002", "R-2026-003"}

    # Issue-date range as an ISO string, the format the frontend datepicker sends.
    by_issue = await svc.list_invoices_paged(issue_from="2026-02-01", issue_to="2026-04-01")
    assert [i.number for i in by_issue.items] == ["R-2026-002"]

    # Due-date range.
    by_due = await svc.list_invoices_paged(due_from="2026-06-15")
    assert [i.number for i in by_due.items] == ["R-2026-003"]

    # Offset paging. The total stays independent of the window. Pages do not overlap.
    first = await svc.list_invoices_paged(limit=2, offset=0)
    second = await svc.list_invoices_paged(limit=2, offset=2)
    assert first.total == 3 and second.total == 3
    assert len(first.items) == 2 and len(second.items) == 1
    ids = {i.id for i in first.items} | {i.id for i in second.items}
    assert len(ids) == 3

    # No hit gives an empty page. The count query and the row query stay identical.
    empty = await svc.list_invoices_paged(q="zzzzzznope")
    assert empty.total == 0 and empty.items == []
