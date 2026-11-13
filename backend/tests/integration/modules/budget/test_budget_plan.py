"""Integration (real Postgres): the Haushaltsplan end to end.

The tests cover the side and the plan switch, the plan with its versions, lines,
contribution and state changes, the allocations that a plan in force writes, and the
guards of the allocation, the revert and the delete of a cost center.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.budget.form_options import budget_field_options
from app.modules.budget.plan_models import BudgetPlan, BudgetPlanLine, BudgetPlanVersion
from app.modules.budget.plan_schemas import (
    PlanCreate,
    PlanLineSet,
    PlanNodeCreate,
    PlanOut,
    PlanStateSet,
    PlanStepIn,
    PlanStepsSet,
    PlanVersionOut,
)
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_models import Budget, BudgetAllocation, FiscalYear
from app.modules.budget.tree_schemas import (
    AllocationSet,
    BudgetNodeCreate,
    BudgetNodeOut,
    BudgetNodeUpdate,
    BudgetTreeNodeOut,
    FiscalYearCreate,
    FiscalYearOut,
    FiscalYearUpdate,
)
from app.modules.gremien.models import Gremium
from app.modules.search.service import SearchService
from app.modules.voting.models import Vote
from app.modules.voting.service import VotingService
from app.shared.errors import AppError, ConflictError, NotFoundError, ValidationProblem

pytestmark = pytest.mark.integration

D = Decimal


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


@dataclass(frozen=True, slots=True)
class Tree:
    """A top-level cost center with one income and one expense group."""

    svc: BudgetTreeService
    top: BudgetNodeOut
    inc: BudgetNodeOut
    exp: BudgetNodeOut
    exp_a: BudgetNodeOut
    exp_b: BudgetNodeOut
    fy: FiscalYearOut


async def _tree(session: AsyncSession, *, sides: bool = True, enabled: bool = True) -> Tree:
    svc = BudgetTreeService(session, actor="tester")
    key = f"P{uuid.uuid4().hex[:8]}"
    top = await svc.create_node(BudgetNodeCreate(key=key, name="VS-Mittel"))
    inc = await svc.create_node(BudgetNodeCreate(key="1", name="Beiträge", parentId=top.id))
    exp = await svc.create_node(BudgetNodeCreate(key="8", name="Zuschüsse", parentId=top.id))
    exp_a = await svc.create_node(BudgetNodeCreate(key="1", name="Fachschaften", parentId=exp.id))
    exp_b = await svc.create_node(BudgetNodeCreate(key="2", name="AKs", parentId=exp.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    if sides:
        await svc.set_side(inc.id, "income")
        await svc.set_side(exp.id, "expense")
    if sides and enabled:
        await svc.set_plan_switch(top.id, True)
    await session.commit()
    return Tree(svc, top, inc, exp, exp_a, exp_b, fy)


def _code(exc: pytest.ExceptionInfo[AppError]) -> str | None:
    return exc.value.code


def _version(plan: PlanOut, number: int = -1) -> PlanVersionOut:
    return plan.versions[number]


def _amounts(version: PlanVersionOut) -> dict[uuid.UUID, Decimal]:
    return {line.budget_id: line.amount for line in version.lines}


async def _allocations(session: AsyncSession, t: Tree) -> dict[uuid.UUID, Decimal]:
    rows = await session.execute(
        select(BudgetAllocation.budget_id, BudgetAllocation.allocated).where(
            BudgetAllocation.fiscal_year_id == t.fy.id
        )
    )
    return {row.budget_id: row.allocated for row in rows}


async def _draft(t: Tree) -> PlanOut:
    """Replace the Stammplan in force of the switch by a fresh plan with a draft."""
    plan = await t.svc.session.scalar(
        select(BudgetPlan).where(BudgetPlan.fiscal_year_id == t.fy.id)
    )
    await t.svc.session.delete(plan)
    await t.svc.session.commit()
    out = await t.svc.create_plan(t.top.id, t.fy.id, PlanCreate())
    await t.svc.session.commit()
    return out


async def _balanced_draft(t: Tree) -> PlanOut:
    plan = await _draft(t)
    vid = _version(plan).id
    await t.svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(100)))
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(60)))
    out = await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(40)))
    await t.svc.session.commit()
    return out


async def _in_force(t: Tree) -> PlanOut:
    plan = await _balanced_draft(t)
    vid = _version(plan).id
    plan = await t.svc.set_plan_state(vid, PlanStateSet(state="in_force"))
    await t.svc.session.commit()
    return plan


async def _steps(t: Tree, *names: str, gremium_id: uuid.UUID | None = None) -> None:
    """Give the budget its plan steps. The first one names the Gremium."""
    await t.svc.set_plan_steps(
        t.top.id,
        PlanStepsSet(
            steps=tuple(
                PlanStepIn(name=name, gremiumId=gremium_id if i == 0 else None)
                for i, name in enumerate(names)
            )
        ),
    )
    await t.svc.session.commit()


async def _allocated(session: AsyncSession, fy_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    rows = (
        await session.execute(
            select(BudgetAllocation.budget_id, BudgetAllocation.allocated).where(
                BudgetAllocation.fiscal_year_id == fy_id
            )
        )
    ).all()
    return {row.budget_id: row.allocated for row in rows}


async def test_side_goes_to_the_subtree_and_to_a_new_child(session: AsyncSession) -> None:
    """The side of a direct child of the top level reaches each node below it.

    Rules: §F/finance/budget/000817, §F/finance/budget/000790.
    """
    t = await _tree(session, enabled=False)
    sides = dict(
        (await session.execute(select(Budget.id, Budget.side).where(Budget.id.in_(
            [t.top.id, t.inc.id, t.exp.id, t.exp_a.id, t.exp_b.id]
        )))).all()
    )
    assert sides == {
        t.top.id: None, t.inc.id: "income", t.exp.id: "expense",
        t.exp_a.id: "expense", t.exp_b.id: "expense",
    }
    child = await t.svc.create_node(BudgetNodeCreate(key="9", name="Neu", parentId=t.exp_a.id))
    assert child.side == "expense"


async def test_a_new_direct_child_of_a_planned_budget_needs_a_side(
    session: AsyncSession,
) -> None:
    """The create takes the side and refuses a direct child without one.

    Rule: §F/finance/budget/000829.
    """
    t = await _tree(session)
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.create_node(BudgetNodeCreate(key="9", name="Neu", parentId=t.top.id))
    assert _code(exc) == "plan_side_missing"
    made = await t.svc.create_node(
        BudgetNodeCreate(key="9", name="Neu", parentId=t.top.id, side="income")
    )
    assert made.side == "income"
    deep = await t.svc.create_node(BudgetNodeCreate(key="1", name="Tief", parentId=made.id))
    assert deep.side == "income"
    with pytest.raises(ValidationProblem) as off:
        await t.svc.create_node(
            BudgetNodeCreate(key="2", name="Tief", parentId=made.id, side="expense")
        )
    assert _code(off) == "side_not_settable"
    free = await _tree(session, enabled=False)
    loose = await free.svc.create_node(BudgetNodeCreate(key="9", name="Neu", parentId=free.top.id))
    assert loose.side is None


async def test_side_is_refused_off_the_first_level(session: AsyncSession) -> None:
    """A top-level node has no side, and a deeper node takes it from its parent.

    Rules: §F/finance/budget/000790, §F/finance/budget/000817.
    """
    t = await _tree(session, sides=False)
    for node in (t.top, t.exp_a):
        with pytest.raises(ValidationProblem) as exc:
            await t.svc.set_side(node.id, "income")
        assert _code(exc) == "side_not_settable"


async def test_side_cannot_change_below_a_planned_amount(session: AsyncSession) -> None:
    """§F/finance/budget/000817: 409 side_in_plan when a plan line of the subtree has an Ansatz."""
    t = await _tree(session)
    plan = await _draft(t)
    assert (await t.svc.set_side(t.exp.id, "income")).side == "income"
    await t.svc.set_side(t.exp.id, "expense")
    await t.svc.set_line(_version(plan).id, t.exp_a.id, PlanLineSet(amount=D(5)))
    assert (await t.svc.set_side(t.exp.id, "expense")).side == "expense"
    with pytest.raises(ConflictError) as exc:
        await t.svc.set_side(t.exp.id, "income")
    assert _code(exc) == "side_in_plan"


async def test_plan_switch_needs_a_top_level_node_with_sides(session: AsyncSession) -> None:
    """422 plan_side_missing while a node below the top level has no side.

    Rules: §F/finance/budget/000817, §F/finance/budget/000814.
    """
    t = await _tree(session, sides=False)
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.set_plan_switch(t.exp.id, True)
    assert _code(exc) == "plan_top_level_only"
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.set_plan_switch(t.top.id, True)
    assert _code(exc) == "plan_side_missing"
    assert (await t.svc.set_plan_switch(t.top.id, False)).plan_enabled is False


async def test_plan_switch_gives_open_years_a_stammplan(session: AsyncSession) -> None:
    """Each open year gets a Stammplan in force from its allocations.

    Rules: §F/finance/budget/000803, §F/finance/budget/000814.
    """
    t = await _tree(session, enabled=False)
    closed = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2025))
    await t.svc.set_allocation(t.top.id, t.fy.id, AllocationSet(allocated=D(100)))
    await t.svc.set_allocation(t.exp.id, t.fy.id, AllocationSet(allocated=D(80)))
    await t.svc.set_allocation(t.exp_a.id, t.fy.id, AllocationSet(allocated=D(30)))
    await t.svc.set_fiscal_year_closed(t.top.id, closed.id, closed=True)

    preview = await t.svc.preview_plan_switch(t.top.id)
    assert [(c.path_key, c.allocated, c.planned, c.year) for c in preview.changes] == [
        (t.top.path_key, D(100), D(30), "2026"),
        (t.exp.path_key, D(80), D(30), "2026"),
    ]
    with pytest.raises(ConflictError) as unconfirmed:
        await t.svc.set_plan_switch(t.top.id, True)
    assert _code(unconfirmed) == "plan_changes_allocations"
    switched = await t.svc.set_plan_switch(t.top.id, True, confirm_changes=True)
    assert switched.plan_enabled is True
    await session.commit()

    plan = await t.svc.get_plan(t.top.id, t.fy.id)
    stamm = _version(plan, 0)
    assert (stamm.number, stamm.state, len(plan.versions)) == (0, "in_force", 1)
    assert stamm.in_force_at is not None
    assert _amounts(stamm) == {
        t.inc.id: D(0), t.exp.id: D(30), t.exp_a.id: D(30), t.exp_b.id: D(0),
    }
    assert await _allocations(session, t) == {
        t.top.id: D(30), t.inc.id: D(0), t.exp.id: D(30), t.exp_a.id: D(30), t.exp_b.id: D(0),
    }
    assert (await t.svc.preview_plan_switch(t.top.id)).changes == ()
    assert {line.path_key for line in stamm.lines} == {
        t.inc.path_key, t.exp.path_key, t.exp_a.path_key, t.exp_b.path_key,
    }
    with pytest.raises(NotFoundError) as exc:
        await t.svc.get_plan(t.top.id, closed.id)
    assert _code(exc) == "plan_not_found"

    before = await session.scalar(select(BudgetPlan.id).where(BudgetPlan.fiscal_year_id == t.fy.id))
    await t.svc.set_plan_switch(t.top.id, True)
    assert before == await session.scalar(
        select(BudgetPlan.id).where(BudgetPlan.fiscal_year_id == t.fy.id)
    )
    tree_top = next(n for n in await t.svc.get_tree() if n.id == t.top.id)
    assert tree_top.plan_enabled is True
    assert {c.side for c in tree_top.children} == {"income", "expense"}


async def test_the_plan_switch_goes_off_only_without_a_decision(session: AsyncSession) -> None:
    """Off deletes a Stammplan of the switch, and a plan with more refuses.

    Rule: §F/finance/budget/000814.
    """
    t = await _tree(session)
    first = await session.scalar(select(BudgetPlan.id).where(BudgetPlan.fiscal_year_id == t.fy.id))
    assert (await t.svc.set_plan_switch(t.top.id, False)).plan_enabled is False
    await session.commit()
    assert await session.scalar(
        select(BudgetPlan.id).where(BudgetPlan.fiscal_year_id == t.fy.id)
    ) is None
    with pytest.raises(ConflictError) as off:
        await t.svc.set_plan_steps(t.top.id, PlanStepsSet(steps=()))
    assert _code(off) == "plan_not_enabled"
    with pytest.raises(ConflictError) as no_plan:
        await t.svc.create_plan(t.top.id, t.fy.id, PlanCreate())
    assert _code(no_plan) == "plan_not_enabled"

    await t.svc.set_plan_switch(t.top.id, True)
    await session.commit()
    second = await session.scalar(
        select(BudgetPlan.id).where(BudgetPlan.fiscal_year_id == t.fy.id)
    )
    assert second not in (None, first)
    await t.svc.create_nachtrag(t.top.id, t.fy.id)
    await session.commit()
    with pytest.raises(ConflictError) as held:
        await t.svc.set_plan_switch(t.top.id, False)
    assert _code(held) == "plan_switch_has_plans"


async def test_a_plan_write_needs_the_switch(session: AsyncSession) -> None:
    """With the switch off, no route writes a plan.

    Rules: §F/finance/budget/000814, §F/finance/budget/000823.
    """
    t = await _tree(session)
    plan = await _draft(t)
    vid = _version(plan).id
    top = await session.get_one(Budget, t.top.id)
    top.plan_enabled = False
    await session.commit()
    with pytest.raises(ConflictError) as line:
        await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(1)))
    assert _code(line) == "plan_not_enabled"
    with pytest.raises(ConflictError) as nachtrag:
        await t.svc.create_nachtrag(t.top.id, t.fy.id)
    assert _code(nachtrag) == "plan_not_enabled"


async def test_plan_routes_check_the_node_and_the_year(session: AsyncSession) -> None:
    t = await _tree(session)
    other = await _tree(session)
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.get_plan(t.exp.id, t.fy.id)
    assert _code(exc) == "plan_top_level_only"
    with pytest.raises(NotFoundError):
        await t.svc.get_plan(t.top.id, other.fy.id)
    with pytest.raises(NotFoundError):
        await t.svc.set_line(uuid.uuid4(), t.exp.id, PlanLineSet(amount=D(1)))


async def test_create_plan(session: AsyncSession) -> None:
    """§F/finance/budget/000791: a year has one plan, and version 0 is the Stammplan."""
    t = await _tree(session, enabled=False)
    with pytest.raises(ConflictError) as exc:
        await t.svc.create_plan(t.top.id, t.fy.id, PlanCreate())
    assert _code(exc) == "plan_not_enabled"
    await t.svc.set_plan_switch(t.top.id, True)
    with pytest.raises(ConflictError) as exc:
        await t.svc.create_plan(t.top.id, t.fy.id, PlanCreate())
    assert _code(exc) == "plan_exists"
    plan = await _draft(t)
    stamm = _version(plan)
    assert (stamm.number, stamm.state, stamm.lines) == (0, "draft", ())
    assert await t.svc.plan_exists(t.fy.id)


async def test_create_plan_copies_the_plan_in_force_of_another_year(
    session: AsyncSession,
) -> None:
    """A new plan takes the lines of the version in force of another year of the budget.

    Rule: §F/finance/budget/000837.
    """
    t = await _tree(session)
    plan = await _balanced_draft(t)
    vid = _version(plan).id
    await t.svc.set_line(
        vid, t.exp_a.id, PlanLineSet(amount=D(60), note="je Fachschaft", transferable=True)
    )
    nxt = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2027))
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.create_plan(t.top.id, nxt.id, PlanCreate(copyFromFiscalYearId=t.fy.id))
    assert _code(exc) == "plan_copy_source_invalid"
    for state in ("in_force",):
        await t.svc.set_plan_state(vid, PlanStateSet(state=state))
    other = await _tree(session)
    for bad in (uuid.uuid4(), other.fy.id, nxt.id):
        with pytest.raises(ValidationProblem) as exc:
            await t.svc.create_plan(t.top.id, nxt.id, PlanCreate(copyFromFiscalYearId=bad))
        assert _code(exc) == "plan_copy_source_invalid"

    copy = _version(
        await t.svc.create_plan(t.top.id, nxt.id, PlanCreate(copyFromFiscalYearId=t.fy.id))
    )
    assert copy.state == "draft"
    assert _amounts(copy) == {
        t.inc.id: D(100), t.exp.id: D(100), t.exp_a.id: D(60), t.exp_b.id: D(40),
    }
    line = next(x for x in copy.lines if x.budget_id == t.exp_a.id)
    assert (line.note, line.transferable, line.name, line.path_key) == (
        "je Fachschaft", True, None, None,
    )


async def test_a_parent_holds_the_sum_of_its_children(session: AsyncSession) -> None:
    """§F/finance/budget/000794: the Ansatz of a parent rises and falls with its children."""
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    plan = await t.svc.set_line(vid, t.exp.id, PlanLineSet(amount=D(90), blocked=D(70)))
    assert _amounts(_version(plan)) == {t.exp.id: D(90)}
    plan = await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(60)))
    assert _amounts(_version(plan)) == {t.exp_a.id: D(60), t.exp.id: D(60)}
    parent = next(x for x in _version(plan).lines if x.budget_id == t.exp.id)
    assert parent.blocked == D(60)
    plan = await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(50)))
    assert _amounts(_version(plan))[t.exp.id] == D(110)
    plan = await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(20)))
    assert _amounts(_version(plan))[t.exp.id] == D(80)
    plan = await t.svc.set_line(vid, t.exp.id, PlanLineSet(amount=D(5), note="Topf"))
    parent = next(x for x in _version(plan).lines if x.budget_id == t.exp.id)
    assert (parent.amount, parent.note) == (D(80), "Topf")
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.set_line(vid, t.exp.id, PlanLineSet(amount=D(500), blocked=D(81)))
    assert _code(exc) == "plan_blocked_above_amount"


async def test_delete_line_lowers_the_parent(session: AsyncSession) -> None:
    """A removed line of a child lowers the parent to the sum that is left.

    Rule: §F/finance/budget/000794.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(60)))
    await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(40)))
    plan = await t.svc.delete_line(vid, t.exp_b.id)
    assert _amounts(_version(plan)) == {t.exp_a.id: D(60), t.exp.id: D(60)}
    plan = await t.svc.delete_line(vid, t.exp_a.id)
    assert _amounts(_version(plan)) == {t.exp.id: D(60)}


async def test_delete_node_lowers_the_parent_of_a_draft(session: AsyncSession) -> None:
    """A deleted Kostenstelle leaves the sum of the children that stay.

    Rules: §F/finance/budget/000794, §F/finance/budget/000820.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(60)))
    await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(40)))
    await session.commit()
    await t.svc.delete_node(t.exp_b.id)
    plan = await t.svc.get_plan(t.top.id, t.fy.id)
    assert _amounts(_version(plan)) == {t.exp_a.id: D(60), t.exp.id: D(60)}


async def test_delete_node_keeps_the_draft_of_a_closed_year(session: AsyncSession) -> None:
    """A closed fiscal year does not change through the delete of a node.

    Rule: §F/finance/budget/000801.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(40)))
    await session.commit()
    await t.svc.set_fiscal_year_closed(t.top.id, t.fy.id, closed=True)
    with pytest.raises(ConflictError) as exc:
        await t.svc.delete_node(t.exp_b.id)
    assert _code(exc) == "fiscal_year_closed"


async def test_a_sum_above_the_largest_amount_is_refused(session: AsyncSession) -> None:
    """A parent sum that the database cannot hold answers 422, not a server error.

    Rule: §F/finance/budget/000794.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D("9999999999.99")))
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(1)))
    assert _code(exc) == "plan_amount_too_large"


async def test_a_set_line_heals_every_parent_of_the_version(session: AsyncSession) -> None:
    """Each write gives every parent of the version the sum of its children.

    Rule: §F/finance/budget/000794.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(60)))
    parent = await session.scalar(
        select(BudgetPlanLine).where(
            BudgetPlanLine.version_id == vid, BudgetPlanLine.budget_id == t.exp.id
        )
    )
    assert parent is not None
    parent.amount = D(999)
    await session.commit()
    plan = await t.svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(1)))
    assert _amounts(_version(plan))[t.exp.id] == D(60)


async def test_set_line_checks_the_node_and_the_marks(session: AsyncSession) -> None:
    """§F/finance/budget/000816: an expense line holds the Vermerke, an income line holds none."""
    t = await _tree(session)
    other = await _tree(session)
    vid = _version(await _draft(t)).id
    for bad in (t.top.id, other.exp.id):
        with pytest.raises(ValidationProblem) as exc:
            await t.svc.set_line(vid, bad, PlanLineSet(amount=D(1)))
        assert _code(exc) == "plan_line_node_invalid"
    with pytest.raises(NotFoundError):
        await t.svc.set_line(vid, uuid.uuid4(), PlanLineSet(amount=D(1)))
    for marks in ({"transferable": True}, {"coverable": True}, {"blocked": D(1)}):
        with pytest.raises(ValidationProblem) as exc:
            payload = PlanLineSet.model_validate({"amount": D(5), **marks})
            await t.svc.set_line(vid, t.inc.id, payload)
        assert _code(exc) == "plan_marks_income"
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(5), blocked=D(6)))
    assert _code(exc) == "plan_blocked_above_amount"
    plan = await t.svc.set_line(
        vid, t.exp_a.id, PlanLineSet(amount=D(5), blocked=D(5), coverable=True, transferable=True)
    )
    line = next(x for x in _version(plan).lines if x.budget_id == t.exp_a.id)
    assert (line.blocked, line.coverable, line.transferable) == (D(5), True, True)
    orphan = Budget(
        id=uuid.uuid4(), parent_id=t.top.id, key="7", path_key=f"{t.top.path_key}-7", name="Ohne"
    )
    session.add(orphan)
    await session.commit()
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.set_line(vid, orphan.id, PlanLineSet(amount=D(1)))
    assert _code(exc) == "plan_side_missing"


async def test_delete_line(session: AsyncSession) -> None:
    """A draft loses a line, but not while a child has one, and a PUT adds it again.

    Rule: §F/finance/budget/000819.
    """
    t = await _tree(session)
    plan = await _balanced_draft(t)
    vid = _version(plan).id
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.delete_line(vid, t.exp.id)
    assert _code(exc) == "plan_line_has_children"
    await t.svc.delete_line(vid, t.exp_a.id)
    plan = await t.svc.delete_line(vid, t.exp_b.id)
    assert set(_amounts(_version(plan))) == {t.inc.id, t.exp.id}
    plan = await t.svc.delete_line(vid, t.exp.id)
    assert set(_amounts(_version(plan))) == {t.inc.id}
    with pytest.raises(NotFoundError) as nf:
        await t.svc.delete_line(vid, t.exp.id)
    assert _code(nf) == "plan_line_not_found"


async def test_plan_steps_of_a_budget(session: AsyncSession) -> None:
    """A budget has an ordered list of steps, each with a name and a Gremium.

    Rule: §F/finance/budget/000823.
    """
    t = await _tree(session)
    assert (await t.svc.get_plan_steps(t.top.id)).steps == ()
    gremium = Gremium(id=uuid.uuid4(), slug=f"g{uuid.uuid4().hex[:8]}", name="StuPa")
    session.add(gremium)
    await session.commit()
    await _steps(t, "Beschluss", "Genehmigung", gremium_id=gremium.id)
    out = await t.svc.get_plan_steps(t.top.id)
    assert [(s.name, s.gremium_name, s.passed_at) for s in out.steps] == [
        ("Beschluss", "StuPa", None),
        ("Genehmigung", None, None),
    ]
    await _steps(t, "Genehmigung")
    assert [s.name for s in (await t.svc.get_plan_steps(t.top.id)).steps] == ["Genehmigung"]
    with pytest.raises(ValidationProblem) as unknown:
        await _steps(t, "Beschluss", gremium_id=uuid.uuid4())
    assert _code(unknown) == "plan_step_gremium_invalid"
    with pytest.raises(ValidationProblem) as below:
        await t.svc.set_plan_steps(t.exp.id, PlanStepsSet(steps=()))
    assert _code(below) == "plan_top_level_only"
    entry = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_PLAN_STEPS_SET)
            .where(AuditEntry.target_id == str(t.top.id))
            .order_by(AuditEntry.id.desc())
        )
    ).first()
    assert entry is not None
    assert entry.data["before"] == [
        {"name": "Beschluss", "gremiumId": str(gremium.id)},
        {"name": "Genehmigung", "gremiumId": None},
    ]
    assert entry.data["after"] == [{"name": "Genehmigung", "gremiumId": None}]


async def test_a_version_passes_the_steps_of_its_budget(session: AsyncSession) -> None:
    """Steps in order, balance first, own record.

    Rules: §F/finance/budget/000792, §F/finance/budget/000795, §F/finance/budget/000824,
    §F/finance/budget/000825, §F/finance/budget/000821.
    """
    t = await _tree(session)
    await _steps(t, "Beschluss", "Genehmigung")
    plan = await _balanced_draft(t)
    vid = _version(plan).id
    assert [(s.name, s.passed_at) for s in _version(plan).steps] == [
        ("Beschluss", None),
        ("Genehmigung", None),
    ]
    for target in ("in_force", "draft"):
        with pytest.raises(ConflictError) as exc:
            await t.svc.set_plan_state(vid, PlanStateSet(state=target))
        assert _code(exc) == "plan_state_invalid"
    await t.svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(99)))
    with pytest.raises(ValidationProblem) as unbalanced:
        await t.svc.pass_next_step(vid)
    assert _code(unbalanced) == "plan_not_balanced"
    await t.svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(100)))

    first = _version(await t.svc.pass_next_step(vid))
    assert first.state == "in_progress"
    assert [s.passed_at is not None for s in first.steps] == [True, False]
    assert {line.name for line in first.lines} == {"Beiträge", "Zuschüsse", "Fachschaften", "AKs"}
    await session.commit()
    await _steps(t, "Anders")
    kept = _version(await t.svc.get_plan(t.top.id, t.fy.id))
    assert [s.name for s in kept.steps] == ["Beschluss", "Genehmigung"]
    with pytest.raises(ConflictError) as early:
        await t.svc.set_plan_state(vid, PlanStateSet(state="in_force"))
    assert _code(early) == "plan_state_invalid"
    second = _version(await t.svc.pass_next_step(vid))
    assert [s.passed_at is not None for s in second.steps] == [True, True]

    draft = _version(await t.svc.set_plan_state(vid, PlanStateSet(state="draft")))
    assert draft.state == "draft"
    assert [(s.name, s.passed_at) for s in draft.steps] == [("Anders", None)]
    assert {line.name for line in draft.lines} == {None}

    await t.svc.pass_next_step(vid)
    with pytest.raises(ConflictError) as none_left:
        await t.svc.pass_next_step(vid)
    assert _code(none_left) == "plan_no_step_left"
    done = _version(await t.svc.set_plan_state(vid, PlanStateSet(state="in_force")))
    assert (done.state, [s.name for s in done.steps]) == ("in_force", ["Anders"])
    with pytest.raises(ConflictError) as over:
        await t.svc.pass_next_step(vid)
    assert _code(over) == "plan_state_invalid"
    step = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_PLAN_STEP)
            .where(AuditEntry.target_id == str(plan.id))
            .order_by(AuditEntry.id.desc())
        )
    ).first()
    assert step is not None
    assert (step.data["step"], step.data["gremiumId"]) == ("Anders", None)
    assert step.data["voteId"] is None


async def test_a_budget_without_steps_goes_from_draft_into_force(session: AsyncSession) -> None:
    """Without steps the draft comes into force, balanced and with its names.

    Rules: §F/finance/budget/000792, §F/finance/budget/000795, §F/finance/budget/000821.
    """
    t = await _tree(session)
    plan = await _balanced_draft(t)
    vid = _version(plan).id
    with pytest.raises(ConflictError) as no_step:
        await t.svc.pass_next_step(vid)
    assert _code(no_step) == "plan_no_step_left"
    await t.svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(99)))
    with pytest.raises(ValidationProblem) as unbalanced:
        await t.svc.set_plan_state(vid, PlanStateSet(state="in_force"))
    assert _code(unbalanced) == "plan_not_balanced"
    await t.svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(100)))
    done = _version(await t.svc.set_plan_state(vid, PlanStateSet(state="in_force")))
    assert (done.state, done.steps) == ("in_force", ())
    assert {line.name for line in done.lines} == {"Beiträge", "Zuschüsse", "Fachschaften", "AKs"}
    with pytest.raises(ConflictError) as back:
        await t.svc.set_plan_state(vid, PlanStateSet(state="draft"))
    assert _code(back) == "plan_state_invalid"


async def test_create_a_cost_centre_in_a_draft(session: AsyncSession) -> None:
    """The cost center and its line come in one request, only in a draft.

    Rules: §F/finance/budget/000830, §F/finance/budget/000793.
    """
    t = await _tree(session)
    await _steps(t, "Beschluss")
    plan = await _balanced_draft(t)
    vid = _version(plan).id
    out = await t.svc.create_plan_node(
        vid, PlanNodeCreate(parentId=t.exp.id, key="3", name="Sport", amount=D(5))
    )
    node = await session.scalar(
        select(Budget).where(Budget.parent_id == t.exp.id, Budget.key == "3")
    )
    assert node is not None
    assert (node.side, node.path_key.endswith("-8-3")) == ("expense", True)
    assert _amounts(_version(out))[node.id] == D(5)
    assert _amounts(_version(out))[t.exp.id] == D(105)
    direct = await t.svc.create_plan_node(
        vid, PlanNodeCreate(parentId=t.top.id, key="2", name="Spenden", side="income", amount=D(5))
    )
    assert len(_version(direct).lines) == 6
    for payload, error, code in (
        (PlanNodeCreate(parentId=t.top.id, key="9", name="X"), ValidationProblem, "plan_side_missing"),  # noqa: E501
        (PlanNodeCreate(parentId=t.exp.id, key="3", name="X"), ConflictError, "budget_key_exists"),
    ):
        with pytest.raises(error) as exc:
            await t.svc.create_plan_node(vid, payload)
        assert _code(exc) == code
    other = await t.svc.create_node(BudgetNodeCreate(key=f"O{uuid.uuid4().hex[:8]}", name="QS"))
    with pytest.raises(ValidationProblem) as foreign:
        await t.svc.create_plan_node(vid, PlanNodeCreate(parentId=other.id, key="1", name="X"))
    assert _code(foreign) == "plan_line_node_invalid"
    await t.svc.pass_next_step(vid)
    with pytest.raises(ConflictError) as locked:
        await t.svc.create_plan_node(vid, PlanNodeCreate(parentId=t.exp.id, key="4", name="X"))
    assert _code(locked) == "plan_version_locked"


async def test_only_a_draft_can_be_edited(session: AsyncSession) -> None:
    """A write to a version that is no draft answers 409 plan_version_locked.

    Rule: §F/finance/budget/000793.
    """
    t = await _tree(session)
    await _steps(t, "Beschluss")
    vid = _version(await _balanced_draft(t)).id
    await t.svc.pass_next_step(vid)
    for write in (
        t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(1))),
        t.svc.delete_line(vid, t.exp_a.id),
    ):
        with pytest.raises(ConflictError) as exc:
            await write
        assert _code(exc) == "plan_version_locked"


async def test_in_force_writes_the_allocations(session: AsyncSession) -> None:
    """§F/finance/budget/000797: the plan in force sets the allocation of each cost center."""
    t = await _tree(session)
    await _in_force(t)
    assert await _allocated(session, t.fy.id) == {
        t.top.id: D(100), t.inc.id: D(0), t.exp.id: D(100),
        t.exp_a.id: D(60), t.exp_b.id: D(40),
    }


async def test_nachtrag(session: AsyncSession) -> None:
    """A Nachtrag copies the version in force and then replaces it.

    Rules: §F/finance/budget/000799, §F/finance/budget/000796.
    """
    t = await _tree(session)
    plan = await _balanced_draft(t)
    with pytest.raises(ConflictError) as exc:
        await t.svc.create_nachtrag(t.top.id, t.fy.id)
    assert _code(exc) == "plan_draft_exists"
    await _in_force_from(t, _version(plan).id)

    plan = await t.svc.create_nachtrag(t.top.id, t.fy.id)
    nachtrag = _version(plan)
    assert (nachtrag.number, nachtrag.state) == (1, "draft")
    assert _amounts(nachtrag) == _amounts(_version(plan, 0))
    assert {line.name for line in nachtrag.lines} == {None}
    with pytest.raises(ConflictError) as exc:
        await t.svc.create_nachtrag(t.top.id, t.fy.id)
    assert _code(exc) == "plan_draft_exists"

    await t.svc.set_line(nachtrag.id, t.inc.id, PlanLineSet(amount=D(120)))
    await t.svc.set_line(nachtrag.id, t.exp_a.id, PlanLineSet(amount=D(80)))
    plan = await _in_force_from(t, nachtrag.id)
    assert [v.state for v in plan.versions] == ["replaced", "in_force"]
    assert await _allocated(session, t.fy.id) == {
        t.top.id: D(120), t.inc.id: D(0), t.exp.id: D(120),
        t.exp_a.id: D(80), t.exp_b.id: D(40),
    }


async def _in_force_from(t: Tree, version_id: uuid.UUID) -> PlanOut:
    plan = await t.svc.set_plan_state(version_id, PlanStateSet(state="in_force"))
    await t.svc.session.commit()
    return plan


async def test_nachtrag_needs_a_plan_in_force(session: AsyncSession) -> None:
    """A Nachtrag without a version in force answers 409 plan_not_in_force.

    Rule: §F/finance/budget/000799.
    """
    t = await _tree(session)
    plan_row = await session.scalar(select(BudgetPlan).where(BudgetPlan.fiscal_year_id == t.fy.id))
    assert plan_row is not None
    version = await session.scalar(
        select(BudgetPlanVersion).where(BudgetPlanVersion.plan_id == plan_row.id)
    )
    assert version is not None
    version.state = "replaced"
    await session.commit()
    with pytest.raises(ConflictError) as exc:
        await t.svc.create_nachtrag(t.top.id, t.fy.id)
    assert _code(exc) == "plan_not_in_force"
    await session.delete(plan_row)
    await session.commit()
    with pytest.raises(NotFoundError) as nf:
        await t.svc.create_nachtrag(t.top.id, t.fy.id)
    assert _code(nf) == "plan_not_found"


async def test_a_closed_year_refuses_plan_writes(session: AsyncSession) -> None:
    """§F/finance/budget/000801: each plan write in a closed year answers 409 fiscal_year_closed."""
    t = await _tree(session)
    vid = _version(await _balanced_draft(t)).id
    nxt = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2027))
    await t.svc.set_fiscal_year_closed(t.top.id, t.fy.id, closed=True)
    await t.svc.set_fiscal_year_closed(t.top.id, nxt.id, closed=True)
    for write in (
        t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(1))),
        t.svc.delete_line(vid, t.exp_a.id),
        t.svc.set_plan_state(vid, PlanStateSet(state="in_force")),
        t.svc.pass_next_step(vid),
        t.svc.create_plan_node(vid, PlanNodeCreate(parentId=t.exp.id, key="7", name="X")),
        t.svc.create_nachtrag(t.top.id, t.fy.id),
        t.svc.create_plan(t.top.id, nxt.id, PlanCreate()),
    ):
        with pytest.raises(ConflictError) as exc:
            await write
        assert _code(exc) == "fiscal_year_closed"


async def test_a_year_with_a_plan_refuses_a_direct_allocation(session: AsyncSession) -> None:
    """§F/finance/budget/000798: 409 allocation_from_plan, and only while the plan switch is on."""
    t = await _tree(session)
    with pytest.raises(ConflictError) as exc:
        await t.svc.set_allocation(t.exp.id, t.fy.id, AllocationSet(allocated=D(5)))
    assert _code(exc) == "allocation_from_plan"
    nxt = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2027))
    await t.svc.set_allocation(t.top.id, nxt.id, AllocationSet(allocated=D(5)))
    await t.svc.set_plan_switch(t.top.id, False)
    await session.commit()
    out = await t.svc.set_allocation(t.top.id, t.fy.id, AllocationSet(allocated=D(5)))
    assert out.allocated == D(5)


async def test_revert_of_a_first_allocation_respects_the_plan(session: AsyncSession) -> None:
    """The revert of an allocation in a year with a plan answers 409 allocation_from_plan.

    Rule: §F/finance/budget/000798.
    """
    t = await _tree(session, enabled=False)
    await t.svc.set_allocation(t.top.id, t.fy.id, AllocationSet(allocated=D(5)))
    await t.svc.set_allocation(t.exp.id, t.fy.id, AllocationSet(allocated=D(5)))
    await t.svc.set_allocation(t.exp_a.id, t.fy.id, AllocationSet(allocated=D(5)))
    entry = (
        await session.scalars(
            select(AuditEntry)
            .where(
                AuditEntry.action == AuditAction.BUDGET_ALLOCATION_SET.value,
                AuditEntry.target_id == str(t.top.id),
            )
            .order_by(AuditEntry.id.desc())
        )
    ).first()
    assert entry is not None
    await t.svc.set_plan_switch(t.top.id, True)
    await session.commit()
    with pytest.raises(ConflictError) as exc:
        await t.svc.revert_audit(entry, "tester")
    assert _code(exc) == "allocation_from_plan"


async def test_delete_of_a_cost_centre_in_a_decided_plan(session: AsyncSession) -> None:
    """A line of a decided version blocks the delete, and a draft line goes with it.

    Rule: §F/finance/budget/000820.
    """
    t = await _tree(session)
    plan = await _balanced_draft(t)
    leaf = await t.svc.create_node(BudgetNodeCreate(key="3", name="Leer", parentId=t.exp.id))
    await t.svc.set_line(_version(plan).id, leaf.id, PlanLineSet(amount=D(0)))
    await session.commit()
    await t.svc.delete_node(leaf.id)
    assert await session.scalar(
        select(BudgetPlanLine.id).where(BudgetPlanLine.budget_id == leaf.id)
    ) is None
    await t.svc.set_plan_state(_version(plan).id, PlanStateSet(state="in_force"))
    await session.commit()
    with pytest.raises(ConflictError) as exc:
        await t.svc.delete_node(t.exp_b.id)
    assert _code(exc) == "budget_in_plan"


async def test_each_plan_change_is_audited(session: AsyncSession) -> None:
    """A new version, a state change and a line change write an audit entry.

    Rule: §F/finance/budget/000802.
    """
    t = await _tree(session)
    plan = await _in_force(t)
    rows = (
        await session.scalars(
            select(AuditEntry).where(AuditEntry.target_id == str(plan.id)).order_by(AuditEntry.id)
        )
    ).all()
    assert [r.action for r in rows] == [
        "budget_plan_version_create",
        "budget_plan_line_set",
        "budget_plan_line_set",
        "budget_plan_line_set",
        "budget_plan_state",
    ]
    assert {r.actor for r in rows} == {"tester"}
    assert rows[0].data["number"] == 0
    assert rows[2].data["raised"] == {str(t.exp.id): "60.00"}
    assert rows[2].data["blocked"] == "0.00"
    assert rows[-1].data["allocations"][str(t.top.id)] == ["0.00", "100.00"]
    assert (rows[-1].data["before"], rows[-1].data["after"]) == ("draft", "in_force")
    assert rows[-1].data["versionId"] == str(plan.versions[0].id)


async def _gremium(session: AsyncSession) -> uuid.UUID:
    gremium = Gremium(id=uuid.uuid4(), slug=f"g{uuid.uuid4().hex[:8]}", name="StuPa")
    session.add(gremium)
    await session.commit()
    return gremium.id


async def _decide(
    session: AsyncSession, vote_id: uuid.UUID, gremium: uuid.UUID, choice: str
) -> None:
    """Open the vote of a step, cast one ballot and close it."""
    voting = VotingService(session)
    now = datetime.now(UTC)
    await voting.open(vote_id, now=now, actor="mgr")
    await voting.cast(
        vote_id, Principal(sub="v1", groups={vote_group_key(gremium)}), choice, now=now
    )
    await voting.close(vote_id, Principal(sub="mgr", roles=["admin"]))


async def test_an_accepted_vote_of_the_gremium_passes_its_step(session: AsyncSession) -> None:
    """The step offers a vote of its Gremium, and the accepted vote passes it.

    Rules: §F/finance/budget/000826, §F/finance/budget/000838.
    """
    t = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", "Genehmigung", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id

    asked = _version(await t.svc.create_step_vote(vid))
    step = asked.steps[0]
    assert (asked.state, step.passed_at, step.vote_status) == ("in_progress", None, "draft")
    assert step.vote_id is not None
    vote = await session.get(Vote, step.vote_id)
    assert vote is not None
    assert (vote.plan_version_id, vote.eligible_group) == (vid, str(gremium))
    assert (vote.application_id, vote.meeting_id) == (None, None)
    assert vote.question == "Haushaltsplan VS-Mittel 2026, Stammplan: Beschluss"
    assert "quorum" not in vote.config or vote.config["quorum"] is None
    with pytest.raises(ConflictError) as twice:
        await t.svc.create_step_vote(vid)
    assert _code(twice) == "plan_step_vote_runs"
    await session.rollback()

    shown = await VotingService(session).get(step.vote_id)
    assert shown.plan_version_id == vid
    assert (await t.svc.plan_of_version(vid)).fiscal_year_id == t.fy.id
    with pytest.raises(NotFoundError):
        await t.svc.plan_of_version(uuid.uuid4())

    await _decide(session, step.vote_id, gremium, "yes")
    done = _version(await t.svc.get_plan(t.top.id, t.fy.id))
    assert [s.passed_at is not None for s in done.steps] == [True, False]
    assert (done.steps[0].vote_status, done.steps[0].vote_result) == ("closed", "passed")
    entry = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_PLAN_STEP)
            .where(AuditEntry.data["versionId"].astext == str(vid))
        )
    ).one()
    assert (entry.data["voteId"], entry.actor) == (str(step.vote_id), "mgr")
    asked_entry = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_PLAN_STEP_VOTE)
            .where(AuditEntry.data["versionId"].astext == str(vid))
        )
    ).one()
    assert asked_entry.data["voteId"] == str(step.vote_id)

    with pytest.raises(ValidationProblem) as no_gremium:
        await t.svc.create_step_vote(vid)
    assert _code(no_gremium) == "plan_step_no_gremium"


async def test_a_refused_vote_leaves_the_step_open(session: AsyncSession) -> None:
    """§F/finance/budget/000826: a refused vote passes nothing, and the step takes a new vote."""
    t = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id
    first = _version(await t.svc.create_step_vote(vid)).steps[0]
    assert first.vote_id is not None
    await _decide(session, first.vote_id, gremium, "no")
    refused = _version(await t.svc.get_plan(t.top.id, t.fy.id))
    assert (refused.state, refused.steps[0].passed_at) == ("in_progress", None)
    assert (refused.steps[0].vote_status, refused.steps[0].vote_result) == ("closed", "rejected")

    second = _version(await t.svc.create_step_vote(vid)).steps[0]
    assert second.vote_id not in (None, first.vote_id)
    assert second.vote_status == "draft"
    await session.delete(await session.get(Vote, second.vote_id))
    row = await session.get(Gremium, gremium)
    assert row is not None
    row.quorum_percent = 50
    await session.commit()
    gone = _version(await t.svc.get_plan(t.top.id, t.fy.id)).steps[0]
    assert (gone.vote_id, gone.vote_status) == (second.vote_id, None)
    third = _version(await t.svc.create_step_vote(vid)).steps[0]
    assert third.vote_id not in (first.vote_id, second.vote_id)
    vote = await session.get(Vote, third.vote_id)
    assert vote is not None
    assert vote.config["quorum"] == {"type": "percent", "value": 50}


async def test_back_to_draft_ends_the_votes_of_the_version(session: AsyncSession) -> None:
    """A draft vote is deleted and an open vote is cancelled.

    Rules: §F/finance/budget/000826, §F/finance/budget/000839.
    """
    t = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id

    draft = _version(await t.svc.create_step_vote(vid)).steps[0].vote_id
    assert draft is not None
    await t.svc.set_plan_state(vid, PlanStateSet(state="draft"))
    await session.commit()
    assert await session.get(Vote, draft) is None
    back = _version(await t.svc.get_plan(t.top.id, t.fy.id))
    assert (back.state, back.steps[0].vote_id, back.steps[0].passed_at) == ("draft", None, None)

    opened = _version(await t.svc.create_step_vote(vid)).steps[0].vote_id
    assert opened is not None
    await VotingService(session).open(opened, now=datetime.now(UTC), actor="mgr")
    await t.svc.set_plan_state(vid, PlanStateSet(state="draft"))
    await session.commit()
    cancelled = await session.get_one(Vote, opened)
    await session.refresh(cancelled)
    assert cancelled.status == "cancelled"


async def test_a_step_with_a_vote_is_not_recorded_by_hand(session: AsyncSession) -> None:
    """§F/finance/budget/000825: only the result of the vote passes a step that has one."""
    t = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id
    vote_id = _version(await t.svc.create_step_vote(vid)).steps[0].vote_id
    assert vote_id is not None
    with pytest.raises(ConflictError) as planned:
        await t.svc.pass_next_step(vid)
    assert _code(planned) == "plan_step_has_vote"
    await _decide(session, vote_id, gremium, "no")
    with pytest.raises(ConflictError) as refused:
        await t.svc.pass_next_step(vid)
    assert _code(refused) == "plan_step_has_vote"

    again = _version(await t.svc.create_step_vote(vid)).steps[0].vote_id
    assert again is not None
    voting = VotingService(session)
    await voting.open(again, now=datetime.now(UTC), actor="mgr")
    await voting.cancel(again, actor="mgr")
    passed = _version(await t.svc.pass_next_step(vid))
    assert passed.steps[0].passed_at is not None


async def test_a_step_of_a_deleted_gremium_takes_no_vote(session: AsyncSession) -> None:
    """A step whose Gremium is gone answers 422 plan_step_no_gremium to a vote.

    Rule: §F/finance/budget/000838.
    """
    t = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", "Genehmigung", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id
    version = await session.get_one(BudgetPlanVersion, vid)
    await t.svc.pass_next_step(vid)
    version.steps = [{**step, "gremiumId": str(uuid.uuid4())} for step in version.steps]
    version.steps = [{**version.steps[0], "passedAt": None}, version.steps[1]]
    await session.commit()
    with pytest.raises(ValidationProblem) as gone:
        await t.svc.create_step_vote(vid)
    assert _code(gone) == "plan_step_no_gremium"


async def test_a_vote_passes_only_the_step_it_decides(session: AsyncSession) -> None:
    """§F/finance/budget/000826: the close of a vote never fails for the state of the plan."""
    t = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id
    assert not await t.svc.pass_step_by_vote(uuid.uuid4(), uuid.uuid4())

    first = _version(await t.svc.create_step_vote(vid)).steps[0]
    assert first.vote_id is not None
    assert not await t.svc.pass_step_by_vote(vid, uuid.uuid4())

    with pytest.raises(ConflictError) as running:
        await t.svc.set_fiscal_year_closed(t.top.id, t.fy.id, closed=True)
    assert _code(running) == "plan_in_progress"
    year = await session.get_one(FiscalYear, t.fy.id)
    year.closed_at = datetime.now(UTC)
    await session.commit()
    await _decide(session, first.vote_id, gremium, "yes")
    year.closed_at = None
    await session.commit()
    kept = _version(await t.svc.get_plan(t.top.id, t.fy.id))
    assert (kept.state, kept.steps[0].passed_at) == ("in_progress", None)
    assert kept.steps[0].vote_result == "passed"


async def test_the_first_child_line_takes_the_ansatz_of_its_parent(session: AsyncSession) -> None:
    """§F/finance/budget/000794: a parent that gets its first child line loses no Ansatz."""
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.set_line(vid, t.exp.id, PlanLineSet(amount=D(90), blocked=D(70), note="Topf"))
    first = _version(await t.svc.set_line(vid, t.exp_a.id, PlanLineSet()))
    lines = {line.budget_id: line for line in first.lines}
    assert (lines[t.exp_a.id].amount, lines[t.exp_a.id].blocked) == (D(90), D(70))
    assert (lines[t.exp.id].amount, lines[t.exp.id].blocked) == (D(90), D(0))
    second = _version(await t.svc.set_line(vid, t.exp_b.id, PlanLineSet()))
    assert _amounts(second)[t.exp_b.id] == D(0)

    created = _version(
        await t.svc.create_plan_node(vid, PlanNodeCreate(parentId=t.exp_b.id, key="1", name="Neu"))
    )
    assert _amounts(created)[t.exp_b.id] == D(0)
    other = await _tree(session)
    other_vid = _version(await _draft(other)).id
    await other.svc.set_line(other_vid, other.exp.id, PlanLineSet(amount=D(90)))
    typed = _version(await other.svc.set_line(other_vid, other.exp_a.id, PlanLineSet(amount=D(5))))
    assert _amounts(typed) == {other.exp.id: D(5), other.exp_a.id: D(5)}


async def test_a_line_request_changes_only_the_fields_it_names(session: AsyncSession) -> None:
    """Two requests that each change one field keep the change of the other.

    Rule: §F/finance/budget/000812.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(90), note="alt", blocked=D(10)))
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(transferable=True))
    out = _version(await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(95))))
    line = next(ln for ln in out.lines if ln.budget_id == t.exp_a.id)
    assert (line.amount, line.note, line.blocked, line.transferable, line.coverable) == (
        D(95), "alt", D(10), True, False,
    )
    cleared = _version(await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(note=None)))
    assert next(ln for ln in cleared.lines if ln.budget_id == t.exp_a.id).note is None


async def test_a_draft_version_is_deleted(session: AsyncSession) -> None:
    """A draft goes, and the plan with it when it has no other version.

    Rules: §F/finance/budget/000835, §F/finance/budget/000793.
    """
    t = await _tree(session)
    plan = await t.svc.create_nachtrag(t.top.id, t.fy.id)
    await session.commit()
    stamm, nachtrag = plan.versions
    with pytest.raises(ConflictError) as decided:
        await t.svc.delete_version(stamm.id)
    assert _code(decided) == "plan_version_locked"
    await t.svc.delete_version(nachtrag.id)
    await session.commit()
    assert [v.number for v in (await t.svc.get_plan(t.top.id, t.fy.id)).versions] == [0]

    alone = _version(await _draft(t)).id
    await t.svc.delete_version(alone)
    await session.commit()
    with pytest.raises(NotFoundError):
        await t.svc.get_plan(t.top.id, t.fy.id)
    entry = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_PLAN_VERSION_DELETE)
            .order_by(AuditEntry.id.desc())
        )
    ).first()
    assert entry is not None
    assert entry.data["planDeleted"] is True


async def test_a_fiscal_year_with_a_decided_plan_is_not_deleted(session: AsyncSession) -> None:
    """A decided plan keeps its year, and a draft goes with the year.

    Rules: §F/finance/budget/000836, §F/finance/budget/000801.
    """
    t = await _tree(session)
    with pytest.raises(ConflictError) as decided:
        await t.svc.delete_fiscal_year(t.top.id, t.fy.id)
    assert _code(decided) == "fiscal_year_has_plan"

    later = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2027))
    drafted = await t.svc.create_plan(t.top.id, later.id, PlanCreate())
    await session.commit()
    await t.svc.delete_fiscal_year(t.top.id, later.id)
    assert await session.get(BudgetPlan, drafted.id) is None
    entry = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_FISCAL_YEAR_DELETE)
            .order_by(AuditEntry.id.desc())
        )
    ).first()
    assert entry is not None
    assert entry.data["planDeleted"] is True


async def test_a_version_without_a_line_does_not_come_into_force(session: AsyncSession) -> None:
    """A version without a line answers 422 plan_empty, into force and at its first step.

    Rule: §F/finance/budget/000792.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    with pytest.raises(ValidationProblem) as empty:
        await t.svc.set_plan_state(vid, PlanStateSet(state="in_force"))
    assert _code(empty) == "plan_empty"
    await _steps(t, "Beschluss")
    with pytest.raises(ValidationProblem) as step:
        await t.svc.pass_next_step(vid)
    assert _code(step) == "plan_empty"


async def test_a_version_in_force_does_not_come_into_force_again(session: AsyncSession) -> None:
    """A second move into force answers 409 plan_state_invalid.

    Rule: §F/finance/budget/000792.
    """
    t = await _tree(session)
    plan = await _in_force(t)
    with pytest.raises(ConflictError) as again:
        await t.svc.set_plan_state(_version(plan).id, PlanStateSet(state="in_force"))
    assert _code(again) == "plan_state_invalid"
    assert "in_force" in str(again.value)


async def test_the_side_of_a_closed_year_does_not_change(session: AsyncSession) -> None:
    """The plan of a closed fiscal year keeps the side of each line.

    Rules: §F/finance/budget/000801, §F/finance/budget/000817.
    """
    t = await _tree(session)
    await t.svc.set_fiscal_year_closed(t.top.id, t.fy.id, closed=True)
    with pytest.raises(ConflictError) as closed:
        await t.svc.set_side(t.exp.id, "income")
    assert _code(closed) == "fiscal_year_closed"
    assert (await t.svc.set_side(t.exp.id, "expense")).side == "expense"


async def test_a_copy_gives_each_parent_the_sum_of_its_children(session: AsyncSession) -> None:
    """§F/finance/budget/000794: a Nachtrag heals a parent that differs from its children."""
    t = await _tree(session)
    plan = await _in_force(t)
    line = await session.scalar(
        select(BudgetPlanLine).where(
            BudgetPlanLine.version_id == _version(plan).id, BudgetPlanLine.budget_id == t.exp.id
        )
    )
    assert line is not None
    line.amount = D(500)
    await session.commit()
    nachtrag = _version(await t.svc.create_nachtrag(t.top.id, t.fy.id))
    assert _amounts(nachtrag)[t.exp.id] == D(100)


async def test_two_creates_of_one_key_answer_a_conflict(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A create that loses the race for a key answers 409, not a server error.

    Rule: §F/finance/budget/000830.
    """
    t = await _tree(session)

    async def _free(self: BudgetTreeService, parent_id: object, key: str) -> bool:
        return False

    monkeypatch.setattr(BudgetTreeService, "_sibling_exists", _free)
    with pytest.raises(ConflictError) as taken:
        await t.svc.create_node(BudgetNodeCreate(key="1", name="Doppelt", parentId=t.exp.id))
    assert _code(taken) == "budget_key_exists"


async def test_an_inactive_cost_centre_hides_the_ones_below_it(session: AsyncSession) -> None:
    """No picker and no search shows a cost center below an inactive one.

    Rule: §F/finance/budget/000834.
    """
    t = await _tree(session)
    await t.svc.update_node(t.exp.id, BudgetNodeUpdate(active=False))
    options = {option.value for option in await budget_field_options(session)}
    assert str(t.inc.id) in options
    assert not options & {str(t.exp.id), str(t.exp_a.id), str(t.exp_b.id)}
    hits = await SearchService(session)._budgets(
        t.top.path_key, Principal(sub="a", roles=["admin"], permissions={"budget.view"}), "de"
    )
    tree = {str(node.id) for node in (t.top, t.inc, t.exp, t.exp_a, t.exp_b)}
    assert {hit.id for hit in hits} & tree == {str(t.top.id), str(t.inc.id)}


async def test_the_tree_names_the_years_that_plan_a_cost_centre(session: AsyncSession) -> None:
    """The tree says in which fiscal years the plan counts each cost center.

    Rule: §F/finance/budget/000818.
    """
    t = await _tree(session)
    plan = await _balanced_draft(t)
    leaf = await t.svc.create_node(BudgetNodeCreate(key="3", name="Neu", parentId=t.exp.id))

    def planned(tree: list[BudgetTreeNodeOut]) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        top = next(n for n in tree if n.id == t.top.id)
        below = [n for child in top.children for n in (child, *child.children)]
        return {n.id: n.planned_in for n in (top, *below)}

    assert set(planned(await t.svc.get_tree()).values()) == {()}
    await _in_force_from(t, _version(plan).id)
    after = planned(await t.svc.get_tree())
    assert after[leaf.id] == ()
    assert {after[n] for n in (t.top.id, t.inc.id, t.exp.id, t.exp_a.id)} == {(t.fy.id,)}


async def test_the_year_of_a_decided_plan_is_fixed(session: AsyncSession) -> None:
    """A fiscal year keeps its number while its plan has a version that left the draft.

    Rule: §F/finance/budget/000836.
    """
    t = await _tree(session)
    with pytest.raises(ConflictError) as decided:
        await t.svc.update_fiscal_year(t.top.id, t.fy.id, FiscalYearUpdate(year=2031))
    assert _code(decided) == "fiscal_year_has_plan"
    await session.rollback()
    assert (
        await t.svc.update_fiscal_year(t.top.id, t.fy.id, FiscalYearUpdate(active=False))
    ).year == 2026
    await _draft(t)
    assert (
        await t.svc.update_fiscal_year(t.top.id, t.fy.id, FiscalYearUpdate(year=2031))
    ).year == 2031


async def test_a_closed_year_refuses_the_revert_of_a_first_allocation(
    session: AsyncSession,
) -> None:
    """The revert of the first allocation of a closed year changes nothing.

    Rule: §F/finance/budget/000252.
    """
    t = await _tree(session, enabled=False)
    await t.svc.set_allocation(t.top.id, t.fy.id, AllocationSet(allocated=D(10)))
    entry = (
        await session.scalars(
            select(AuditEntry).where(
                AuditEntry.action == AuditAction.BUDGET_ALLOCATION_SET.value,
                AuditEntry.target_id == str(t.top.id),
            )
        )
    ).one()
    await t.svc.set_fiscal_year_closed(t.top.id, t.fy.id, closed=True)
    with pytest.raises(ConflictError) as closed:
        await t.svc.revert_audit(entry, "tester")
    assert _code(closed) == "fiscal_year_closed"
    assert (await _allocations(session, t))[t.top.id] == D(10)


async def test_a_request_passes_only_the_step_it_names(session: AsyncSession) -> None:
    """Two requests for one step pass one step.

    Rule: §F/finance/budget/000841.
    """
    t = await _tree(session)
    await _steps(t, "Beschluss", "Genehmigung")
    vid = _version(await _balanced_draft(t)).id
    await t.svc.pass_next_step(vid, expected=0)
    await session.commit()
    with pytest.raises(ConflictError) as again:
        await t.svc.pass_next_step(vid, expected=0)
    assert _code(again) == "plan_step_not_next"
    await session.rollback()
    passed = _version(await t.svc.pass_next_step(vid, expected=1))
    assert all(step.passed_at is not None for step in passed.steps)


async def test_an_income_side_takes_the_vermerke_off_the_draft_line(
    session: AsyncSession,
) -> None:
    """A Kostenstelle that becomes income keeps no Vermerk in a draft.

    Rules: §F/finance/budget/000816, §F/finance/budget/000817.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(transferable=True, coverable=True))
    await session.commit()
    await t.svc.set_side(t.exp.id, "income")
    await session.commit()
    session.expire_all()
    line = next(
        ln for ln in _version(await t.svc.get_plan(t.top.id, t.fy.id)).lines
        if ln.budget_id == t.exp_a.id
    )
    assert (line.transferable, line.coverable) == (False, False)
    entry = (
        await session.scalars(
            select(AuditEntry)
            .where(
                AuditEntry.action == AuditAction.BUDGET_SIDE_SET.value,
                AuditEntry.target_id == str(t.exp.id),
            )
            .order_by(AuditEntry.id.desc())
        )
    ).first()
    assert entry is not None
    assert entry.data["clearedMarks"] == [
        {
            "versionId": str(vid),
            "budgetId": str(t.exp_a.id),
            "transferable": True,
            "coverable": True,
            "blocked": "0.00",
        }
    ]


async def test_a_vermerk_of_a_decided_plan_keeps_the_side(session: AsyncSession) -> None:
    """A Kostenstelle with a Vermerk in a decided version does not become income.

    Rules: §F/finance/budget/000816, §F/finance/budget/000817.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(transferable=True))
    await t.svc.set_plan_state(vid, PlanStateSet(state="in_force"))
    await session.commit()
    with pytest.raises(ConflictError) as exc:
        await t.svc.set_side(t.exp.id, "income")
    assert _code(exc) == "side_in_plan"


async def test_the_delete_of_a_budget_names_its_plans(session: AsyncSession) -> None:
    """The audit entry of a deleted budget names each plan that goes with it.

    Rule: §F/finance/budget/000802.
    """
    svc = BudgetTreeService(session, actor="tester")
    top = await svc.create_node(BudgetNodeCreate(key=f"D{uuid.uuid4().hex[:8]}", name="Leer"))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    await svc.set_plan_switch(top.id, True)
    await session.commit()
    plan = await svc.get_plan(top.id, fy.id)
    await svc.delete_node(top.id)
    entry = (
        await session.scalars(
            select(AuditEntry).where(
                AuditEntry.action == AuditAction.BUDGET_NODE_DELETE.value,
                AuditEntry.target_id == str(top.id),
            )
        )
    ).one()
    assert entry.data["deletedPlans"] == [
        {"planId": str(plan.id), "year": 2026, "versionIds": [str(plan.versions[0].id)]}
    ]


async def test_plan_entries_keep_the_names_of_what_they_change(session: AsyncSession) -> None:
    """A plan entry names the budget, the year and the Kostenstelle, so it reads after a delete.

    Rule: §F/finance/budget/000802.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(5)))
    await t.svc.delete_line(vid, t.exp_a.id)
    await session.commit()
    entries = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action.like("budget_plan_%"))
            .order_by(AuditEntry.id.desc())
            .limit(3)
        )
    ).all()
    removed, added, created = entries
    assert (created.data["budget"], created.data["year"]) == (t.top.path_key, 2026)
    assert (added.data["pathKey"], added.data["name"]) == (t.exp_a.path_key, "Fachschaften")
    assert (removed.data["pathKey"], removed.data["amount"]) == (t.exp_a.path_key, None)


@pytest.mark.parametrize("write", ["delete_node", "close", "side", "steps", "step", "year"])
async def test_a_write_beside_a_plan_waits_for_the_lock_of_its_budget(
    session: AsyncSession, write: str
) -> None:
    """Each write that a plan depends on takes the lock of the top-level budget first.

    Two such writes at the same moment then run one after the other, and none ends in
    a deadlock or in a state that the rules forbid.
    Rules: §F/finance/budget/000793, §F/finance/budget/000801, §F/finance/budget/000820.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await session.commit()
    maker = async_sessionmaker(session.bind, expire_on_commit=False)

    async def run() -> None:
        async with maker() as other:
            svc = BudgetTreeService(other, actor="tester")
            match write:
                case "delete_node":
                    await svc.delete_node(t.exp_b.id)
                case "close":
                    await svc.set_fiscal_year_closed(t.top.id, t.fy.id, closed=True)
                case "side":
                    await svc.set_side(t.exp.id, "expense")
                case "steps":
                    await svc.set_plan_steps(t.top.id, PlanStepsSet(steps=()))
                case "step":
                    await svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(1)))
                case _:
                    await svc.update_fiscal_year(t.top.id, t.fy.id, FiscalYearUpdate(year=2031))
            await other.commit()

    async with maker() as holder:
        await holder.execute(
            select(Budget.id).where(Budget.id == t.top.id).with_for_update()
        )
        task = asyncio.create_task(run())
        await asyncio.sleep(0.3)
        assert not task.done()
        await holder.commit()
    await asyncio.wait_for(task, 10)


async def test_deletes_name_the_plan_data_that_goes_with_them(session: AsyncSession) -> None:
    """The audit entry of a delete names the lines, versions and plans it removes.

    Rule: §F/finance/budget/000802.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(60)))
    await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(40)))
    await session.commit()
    await t.svc.delete_node(t.exp_b.id)
    gone = (
        await session.scalars(
            select(AuditEntry).where(
                AuditEntry.action == AuditAction.BUDGET_NODE_DELETE.value,
                AuditEntry.target_id == str(t.exp_b.id),
            )
        )
    ).one()
    assert gone.data["draftLines"] == [
        {"versionId": str(vid), "previousAmount": "40.00", "lowered": {str(t.exp.id): "60.00"}}
    ]
    await session.commit()
    later = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2027))
    drafted = await t.svc.create_plan(t.top.id, later.id, PlanCreate())
    await session.commit()
    await t.svc.delete_fiscal_year(t.top.id, later.id)
    year = (
        await session.scalars(
            select(AuditEntry).where(
                AuditEntry.action == AuditAction.BUDGET_FISCAL_YEAR_DELETE.value,
                AuditEntry.target_id == str(later.id),
            )
        )
    ).one()
    assert (year.data["planId"], year.data["versionIds"]) == (
        str(drafted.id),
        [str(drafted.versions[0].id)],
    )

    other = await _tree(session)
    stamm = await other.svc.get_plan(other.top.id, other.fy.id)
    await other.svc.set_plan_switch(other.top.id, False)
    off = (
        await session.scalars(
            select(AuditEntry)
            .where(
                AuditEntry.action == AuditAction.BUDGET_PLAN_SWITCH.value,
                AuditEntry.target_id == str(other.top.id),
            )
            .order_by(AuditEntry.id.desc())
        )
    ).first()
    assert off is not None
    assert off.data["deletedVersions"] == [str(stamm.versions[0].id)]


async def test_a_key_taken_at_the_same_moment_is_a_conflict(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key that another request took after the read answers 409, not a 500.

    Rules: §F/finance/budget/000246, §F/finance/budget/000817.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id

    async def _unseen(_parent: object, _key: str) -> bool:
        return False

    monkeypatch.setattr(t.svc, "_sibling_exists", _unseen)
    with pytest.raises(ConflictError) as taken:
        await t.svc.create_plan_node(
            vid, PlanNodeCreate(parentId=t.exp.id, key="1", name="Doppelt")
        )
    assert _code(taken) == "budget_key_exists"
    await session.rollback()
    with pytest.raises(ValidationProblem) as off:
        await t.svc.create_plan_node(
            vid, PlanNodeCreate(parentId=t.exp.id, key="7", name="Tief", side="income")
        )
    assert _code(off) == "side_not_settable"


async def test_the_preview_counts_with_sides_that_are_not_saved(session: AsyncSession) -> None:
    """The form shows the changed allocations before it saves a side.

    Rules: §F/finance/budget/000803, §F/finance/budget/000840.
    """
    t = await _tree(session, sides=False)
    await t.svc.set_allocation(t.top.id, t.fy.id, AllocationSet(allocated=D(100)))
    await t.svc.set_allocation(t.inc.id, t.fy.id, AllocationSet(allocated=D(20)))
    await t.svc.set_allocation(t.exp.id, t.fy.id, AllocationSet(allocated=D(80)))
    await t.svc.set_allocation(t.exp_a.id, t.fy.id, AllocationSet(allocated=D(30)))
    await session.commit()
    preview = await t.svc.preview_plan_switch(
        t.top.id, {t.inc.id: "income", t.exp.id: "expense"}
    )
    await session.rollback()
    assert [(c.path_key, c.allocated, c.planned) for c in preview.changes] == [
        (t.top.path_key, D(100), D(30)),
        (t.inc.path_key, D(20), D(0)),
        (t.exp.path_key, D(80), D(30)),
    ]
    sides = (
        await session.scalars(select(Budget.side).where(Budget.id.in_([t.inc.id, t.exp.id])))
    ).all()
    assert list(sides) == [None, None]


async def test_a_plan_that_went_while_a_write_waited_is_not_found(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that waited for the lock while its plan was deleted answers 404.

    Rule: §F/finance/budget/000793.
    """
    t = await _tree(session)
    plan = await _draft(t)
    vid = _version(plan).id
    await session.commit()
    await t.svc._lock_top_of_plan(uuid.uuid4())

    async def plan_goes(plan_id: uuid.UUID) -> None:
        await session.execute(delete(BudgetPlan).where(BudgetPlan.id == plan_id))

    monkeypatch.setattr(t.svc, "_lock_top_of_plan", plan_goes)
    with pytest.raises(NotFoundError):
        await t.svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(1)))
