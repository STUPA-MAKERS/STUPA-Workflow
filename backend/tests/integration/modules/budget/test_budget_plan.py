"""Integration (real Postgres): the Haushaltsplan end to end.

The tests cover the side and the plan switch, the plan with its versions, lines,
contribution and state changes, the allocations that a plan in force writes, and the
guards of the allocation, the revert and the delete of a cost center.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
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
from app.modules.budget.tree_models import Budget, BudgetAllocation
from app.modules.budget.tree_schemas import (
    AllocationSet,
    BudgetNodeCreate,
    BudgetNodeOut,
    FiscalYearCreate,
    FiscalYearOut,
)
from app.modules.gremien.models import Gremium
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
    """§000817: the side of a direct child of the top level reaches each node below it."""
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


async def test_side_is_refused_off_the_first_level(session: AsyncSession) -> None:
    """§000790: a top-level node has no side, and a deeper node takes it from its parent."""
    t = await _tree(session, sides=False)
    for node in (t.top, t.exp_a):
        with pytest.raises(ValidationProblem) as exc:
            await t.svc.set_side(node.id, "income")
        assert _code(exc) == "side_not_settable"


async def test_side_cannot_change_below_a_planned_amount(session: AsyncSession) -> None:
    """§000817: 409 side_in_plan when a plan line of the subtree has an Ansatz."""
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
    """§000817: 422 plan_side_missing while a node below the top level has no side."""
    t = await _tree(session, sides=False)
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.set_plan_switch(t.exp.id, True)
    assert _code(exc) == "plan_top_level_only"
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.set_plan_switch(t.top.id, True)
    assert _code(exc) == "plan_side_missing"
    assert (await t.svc.set_plan_switch(t.top.id, False)).plan_enabled is False


async def test_plan_switch_gives_open_years_a_stammplan(session: AsyncSession) -> None:
    """§000803: each open year gets a Stammplan in force from its allocations."""
    t = await _tree(session, enabled=False)
    closed = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2025))
    await t.svc.set_allocation(t.top.id, t.fy.id, AllocationSet(allocated=D(100)))
    await t.svc.set_allocation(t.exp.id, t.fy.id, AllocationSet(allocated=D(80)))
    await t.svc.set_allocation(t.exp_a.id, t.fy.id, AllocationSet(allocated=D(30)))
    await t.svc.set_fiscal_year_closed(t.top.id, closed.id, closed=True)

    assert (await t.svc.set_plan_switch(t.top.id, True)).plan_enabled is True
    await session.commit()

    plan = await t.svc.get_plan(t.top.id, t.fy.id)
    stamm = _version(plan, 0)
    assert (stamm.number, stamm.state, len(plan.versions)) == (0, "in_force", 1)
    assert stamm.in_force_at is not None
    assert _amounts(stamm) == {
        t.inc.id: D(0), t.exp.id: D(80), t.exp_a.id: D(30), t.exp_b.id: D(0),
    }
    assert {line.path_key for line in stamm.lines} == {
        t.inc.path_key, t.exp.path_key, t.exp_a.path_key, t.exp_b.path_key,
    }
    with pytest.raises(NotFoundError) as exc:
        await t.svc.get_plan(t.top.id, closed.id)
    assert _code(exc) == "plan_not_found"

    before = await session.scalar(select(BudgetPlan.id).where(BudgetPlan.fiscal_year_id == t.fy.id))
    await t.svc.set_plan_switch(t.top.id, True)
    await t.svc.set_plan_switch(t.top.id, False)
    await t.svc.set_plan_switch(t.top.id, True)
    after = await session.scalar(select(BudgetPlan.id).where(BudgetPlan.fiscal_year_id == t.fy.id))
    assert before == after
    tree_top = next(n for n in await t.svc.get_tree() if n.id == t.top.id)
    assert tree_top.plan_enabled is True
    assert {c.side for c in tree_top.children} == {"income", "expense"}


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
    """§000791: a year has one plan, and version 0 is the Stammplan."""
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


async def test_set_line_raises_the_parent(session: AsyncSession) -> None:
    """§000794: a sum of children above the parent raises the parent."""
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    plan = await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(60)))
    assert _amounts(_version(plan)) == {t.exp_a.id: D(60), t.exp.id: D(60)}
    plan = await t.svc.set_line(vid, t.exp.id, PlanLineSet(amount=D(90), note="Topf"))
    plan = await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(20)))
    assert _amounts(_version(plan))[t.exp.id] == D(90)
    plan = await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(50)))
    assert _amounts(_version(plan))[t.exp.id] == D(110)
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.set_line(vid, t.exp.id, PlanLineSet(amount=D(109)))
    assert _code(exc) == "plan_line_below_children"


async def test_set_line_checks_the_node_and_the_marks(session: AsyncSession) -> None:
    """§000816: an expense line holds the Vermerke, an income line holds none."""
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
    orphan = await t.svc.create_node(BudgetNodeCreate(key="7", name="Ohne", parentId=t.top.id))
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.set_line(vid, orphan.id, PlanLineSet(amount=D(1)))
    assert _code(exc) == "plan_side_missing"


async def test_delete_line(session: AsyncSession) -> None:
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
    """§000823: a budget has an ordered list of steps, each with a name and a Gremium."""
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
        await t.svc.set_plan_steps(t.exp.id, PlanStepsSet())
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
    assert entry.data["before"] == ["Beschluss", "Genehmigung"]
    assert entry.data["after"] == ["Genehmigung"]


async def test_a_version_passes_the_steps_of_its_budget(session: AsyncSession) -> None:
    """§000792, §000795, §000824, §000825: steps in order, balance first, own record."""
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
    """§000792: without steps the draft comes into force, balanced and with its names."""
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
    """§000830: the cost center and its line come in one request, only in a draft."""
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
    assert _code(locked) == "plan_version_not_draft"


async def test_only_a_draft_can_be_edited(session: AsyncSession) -> None:
    """§000793: a write to a version that is no draft answers 409 plan_version_locked."""
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
    """§000797: the plan in force sets the allocation of each cost center."""
    t = await _tree(session)
    await _in_force(t)
    assert await _allocated(session, t.fy.id) == {
        t.top.id: D(100), t.inc.id: D(0), t.exp.id: D(100),
        t.exp_a.id: D(60), t.exp_b.id: D(40),
    }


async def test_nachtrag(session: AsyncSession) -> None:
    """§000799, §000796: a Nachtrag copies the version in force and then replaces it."""
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
    """§000801: each plan write in a closed year answers 409 fiscal_year_closed."""
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
    """§000798: 409 allocation_from_plan, and only while the plan switch is on."""
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
    t = await _tree(session, enabled=False)
    await t.svc.set_allocation(t.top.id, t.fy.id, AllocationSet(allocated=D(5)))
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
    """§000802: a new version, a state change and a line change write an audit entry."""
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
    assert rows[2].data["raised"] == {str(t.exp.id): "60"}
    assert (rows[-1].data["before"], rows[-1].data["after"]) == ("draft", "in_force")
    assert rows[-1].data["versionId"] == str(plan.versions[0].id)
