"""Integration (real Postgres): the Haushaltsplan end to end.

The tests cover the side and the plan switch, the plan with its versions, lines,
contribution and state changes, the allocations that a plan in force writes, and the
guards of the allocation, the revert and the delete of a cost center.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
    PlanStateByHand,
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
    ExpenseCreate,
    FiscalYearCreate,
    FiscalYearOut,
    FiscalYearUpdate,
)
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.search.service import SearchService
from app.modules.site_config.export_logo import ExportLogo, active_export_logo
from app.modules.site_config.models import SiteConfigVersion
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteCreateInternal
from app.modules.voting.service import VotingService
from app.shared.config_schemas import VoteConfig
from app.shared.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationProblem,
)

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


async def _tree(session: AsyncSession, *, enabled: bool = True) -> Tree:
    svc = BudgetTreeService(session, actor="tester")
    key = f"P{uuid.uuid4().hex[:8]}"
    top = await svc.create_node(BudgetNodeCreate(key=key, name="VS-Mittel"))
    inc = await svc.create_node(BudgetNodeCreate(key="1", name="Beiträge", parentId=top.id))
    exp = await svc.create_node(BudgetNodeCreate(key="8", name="Zuschüsse", parentId=top.id))
    exp_a = await svc.create_node(BudgetNodeCreate(key="1", name="Fachschaften", parentId=exp.id))
    exp_b = await svc.create_node(BudgetNodeCreate(key="2", name="AKs", parentId=exp.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    if enabled:
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


async def _sided(t: Tree, version_id: uuid.UUID) -> PlanOut:
    """Give the two Titel of the tree their sides in a draft version."""
    await t.svc.set_line(version_id, t.inc.id, PlanLineSet(side="income"))
    out = await t.svc.set_line(version_id, t.exp.id, PlanLineSet(side="expense"))
    await t.svc.session.commit()
    return out


async def _draft(t: Tree, *, sides: bool = True) -> PlanOut:
    """Replace the draft of the switch by a fresh plan with a draft.

    With `sides` the draft holds the lines of the two Titel, each with its side and
    an Ansatz of 0.
    """
    plan = await t.svc.session.scalar(
        select(BudgetPlan).where(BudgetPlan.fiscal_year_id == t.fy.id)
    )
    await t.svc.session.delete(plan)
    await t.svc.session.commit()
    out = await t.svc.create_plan(t.top.id, t.fy.id, PlanCreate())
    await t.svc.session.commit()
    return await _sided(t, _version(out).id) if sides else out


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


async def test_a_line_below_a_titel_has_the_side_of_the_titel(session: AsyncSession) -> None:
    """The side of the line of a Titel reaches each line below it in the same version.

    Rule: §F/finance/budget/000853.
    """
    t = await _tree(session)
    plan = await _draft(t, sides=False)
    vid = _version(plan).id
    plan = await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(5)))
    assert {line.budget_id: line.side for line in _version(plan).lines} == {
        t.exp.id: None, t.exp_a.id: None,
    }
    plan = await t.svc.set_line(vid, t.exp.id, PlanLineSet(side="expense"))
    assert {line.budget_id: line.side for line in _version(plan).lines} == {
        t.exp.id: "expense", t.exp_a.id: "expense",
    }
    stored = dict(
        (
            await session.execute(
                select(BudgetPlanLine.budget_id, BudgetPlanLine.side).where(
                    BudgetPlanLine.version_id == vid
                )
            )
        ).all()
    )
    assert stored == {t.exp.id: "expense", t.exp_a.id: None}
    assert _amounts(_version(plan)) == {t.exp.id: D(5), t.exp_a.id: D(5)}
    tree_top = next(n for n in await t.svc.get_tree() if n.id == t.top.id)
    assert "side" not in tree_top.model_dump(by_alias=True)


async def test_a_node_is_created_without_a_side(session: AsyncSession) -> None:
    """The tree holds no side, so the create of a node asks for none.

    Rules: §F/finance/budget/000853, §F/finance/budget/000829.
    """
    t = await _tree(session)
    made = await t.svc.create_node(BudgetNodeCreate(key="9", name="Neu", parentId=t.top.id))
    assert "side" not in made.model_dump(by_alias=True)
    with pytest.raises(ValueError, match="side"):
        BudgetNodeCreate.model_validate(
            {"key": "2", "name": "Tief", "parentId": str(made.id), "side": "expense"}
        )


async def test_side_is_refused_off_the_first_level(session: AsyncSession) -> None:
    """Only the line of a Titel takes a side.

    Rule: §F/finance/budget/000853.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(side="income"))
    assert _code(exc) == "side_not_settable"
    await session.rollback()
    with pytest.raises(ValidationProblem) as top:
        await t.svc.set_line(vid, t.top.id, PlanLineSet(side="income"))
    assert _code(top) == "plan_line_node_invalid"


async def test_a_side_changes_in_a_draft_with_its_amounts(session: AsyncSession) -> None:
    """A Titel with an Ansatz changes its side in a draft, and only there.

    Rules: §F/finance/budget/000853, §F/finance/budget/000793.
    """
    t = await _tree(session)
    plan = await _balanced_draft(t)
    vid = _version(plan).id
    moved = _version(await t.svc.set_line(vid, t.exp.id, PlanLineSet(side="income")))
    assert {line.budget_id: (line.side, line.amount) for line in moved.lines} == {
        t.inc.id: ("income", D(100)),
        t.exp.id: ("income", D(100)),
        t.exp_a.id: ("income", D(60)),
        t.exp_b.id: ("income", D(40)),
    }
    with pytest.raises(ValidationProblem) as unbalanced:
        await t.svc.set_plan_state(vid, PlanStateSet(state="in_force"))
    assert _code(unbalanced) == "plan_not_balanced"
    await session.rollback()
    await t.svc.set_plan_state(vid, PlanStateSet(state="in_force"))
    await session.commit()
    with pytest.raises(ConflictError) as locked:
        await t.svc.set_line(vid, t.exp.id, PlanLineSet(side="income"))
    assert _code(locked) == "plan_version_locked"


async def test_a_titel_without_a_side_keeps_the_version_in_the_draft(
    session: AsyncSession,
) -> None:
    """A version leaves the draft only when each Titel has a side.

    Rule: §F/finance/budget/000853.
    """
    t = await _tree(session)
    await _steps(t, "Beschluss")
    vid = _version(await _draft(t, sides=False)).id
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(0)))
    await t.svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(0)))
    await session.commit()
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.pass_next_step(vid)
    assert _code(exc) == "plan_side_missing"
    assert [e.msg for e in exc.value.errors or ()] == sorted([t.inc.path_key, t.exp.path_key])
    await _steps(t)
    with pytest.raises(ValidationProblem) as force:
        await t.svc.set_plan_state(vid, PlanStateSet(state="in_force"))
    assert _code(force) == "plan_side_missing"
    await _sided(t, vid)
    done = _version(await t.svc.set_plan_state(vid, PlanStateSet(state="in_force")))
    assert done.state == "in_force"


async def test_plan_switch_needs_a_top_level_node(session: AsyncSession) -> None:
    """§F/finance/budget/000814: only a top-level node has the plan switch."""
    t = await _tree(session, enabled=False)
    with pytest.raises(ValidationProblem) as exc:
        await t.svc.set_plan_switch(t.exp.id, True)
    assert _code(exc) == "plan_top_level_only"
    assert (await t.svc.set_plan_switch(t.top.id, False)).plan_enabled is False


async def test_plan_switch_gives_open_years_a_draft(session: AsyncSession) -> None:
    """Each open year gets a draft from its allocations, and no allocation changes.

    Rules: §F/finance/budget/000854, §F/finance/budget/000803, §F/finance/budget/000814.
    """
    t = await _tree(session, enabled=False)
    closed = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2025))
    await t.svc.set_allocation(t.top.id, t.fy.id, AllocationSet(allocated=D(100)))
    await t.svc.set_allocation(t.exp.id, t.fy.id, AllocationSet(allocated=D(80)))
    await t.svc.set_allocation(t.exp_a.id, t.fy.id, AllocationSet(allocated=D(30)))
    await t.svc.set_fiscal_year_closed(t.top.id, closed.id, closed=True)
    before = await _allocations(session, t)

    switched = await t.svc.set_plan_switch(t.top.id, True)
    assert switched.plan_enabled is True
    await session.commit()

    plan = await t.svc.get_plan(t.top.id, t.fy.id)
    first = _version(plan, 0)
    assert (first.number, first.state, len(plan.versions)) == (0, "draft", 1)
    assert first.in_force_at is None
    assert _amounts(first) == {
        t.inc.id: D(0), t.exp.id: D(30), t.exp_a.id: D(30), t.exp_b.id: D(0),
    }
    assert {(line.side, line.name, line.path_key) for line in first.lines} == {(None, None, None)}
    assert await _allocations(session, t) == before
    with pytest.raises(NotFoundError) as exc:
        await t.svc.get_plan(t.top.id, closed.id)
    assert _code(exc) == "plan_not_found"

    kept = await session.scalar(select(BudgetPlan.id).where(BudgetPlan.fiscal_year_id == t.fy.id))
    await t.svc.set_plan_switch(t.top.id, True)
    assert kept == await session.scalar(
        select(BudgetPlan.id).where(BudgetPlan.fiscal_year_id == t.fy.id)
    )
    tree_top = next(n for n in await t.svc.get_tree() if n.id == t.top.id)
    assert tree_top.plan_enabled is True
    entry = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_PLAN_SWITCH)
            .where(AuditEntry.target_id == str(t.top.id))
        )
    ).one()
    assert entry.data["createdPlans"] == [str(plan.id)]
    assert "allocations" not in entry.data


async def test_the_plan_switch_goes_off_only_without_a_decision(session: AsyncSession) -> None:
    """Off deletes a draft of the switch, and a plan with more refuses.

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
    await _in_force(t)
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
    plan = await _draft(t, sides=False)
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
    await session.execute(delete(BudgetPlan).where(BudgetPlan.fiscal_year_id == nxt.id))
    await session.commit()
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
    vid = _version(await _draft(t, sides=False)).id
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
    vid = _version(await _draft(t, sides=False)).id
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
    vid = _version(await _draft(t, sides=False)).id
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


async def test_a_side_sum_above_the_largest_amount_is_refused(session: AsyncSession) -> None:
    """A sum of a side that the allocation cannot hold answers 422 at the line and at the state.

    Rule: §F/finance/budget/000794.
    """
    t = await _tree(session)
    more = await t.svc.create_node(
        BudgetNodeCreate(key="9", name="Sonstiges", parentId=t.top.id)
    )
    gain = await t.svc.create_node(
        BudgetNodeCreate(key="2", name="Spenden", parentId=t.top.id)
    )
    vid = _version(await _draft(t)).id
    await t.svc.set_line(vid, more.id, PlanLineSet(side="expense"))
    await t.svc.set_line(vid, gain.id, PlanLineSet(side="income"))
    largest = D("9999999999.99")
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=largest))
    await t.svc.set_line(vid, t.inc.id, PlanLineSet(amount=largest))
    await session.commit()
    with pytest.raises(ValidationProblem) as at_line:
        await t.svc.set_line(vid, more.id, PlanLineSet(amount=D(1)))
    assert _code(at_line) == "plan_amount_too_large"
    await session.rollback()
    with pytest.raises(ValidationProblem) as at_income:
        await t.svc.set_line(vid, gain.id, PlanLineSet(amount=D(1)))
    assert _code(at_income) == "plan_amount_too_large"
    await session.rollback()
    await t.svc.set_line(vid, more.id, PlanLineSet(amount=D(0)))
    await t.svc.set_line(vid, gain.id, PlanLineSet(amount=D(0)))
    for node in (more, gain):
        line = await session.scalar(
            select(BudgetPlanLine).where(
                BudgetPlanLine.version_id == vid, BudgetPlanLine.budget_id == node.id
            )
        )
        assert line is not None
        line.amount = D(1)
    await session.commit()
    with pytest.raises(ValidationProblem) as at_state:
        await t.svc.set_plan_state(vid, PlanStateSet(state="in_force"))
    assert _code(at_state) == "plan_amount_too_large"


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
    plan = await t.svc.set_line(vid, orphan.id, PlanLineSet(amount=D(1)))
    assert next(x for x in _version(plan).lines if x.budget_id == orphan.id).side is None


def _coverable(plan: PlanOut) -> dict[uuid.UUID, bool]:
    return {line.budget_id: line.coverable for line in _version(plan).lines}


async def _default_on(t: Tree, on: bool = True) -> None:
    out = await t.svc.update_node(t.top.id, BudgetNodeUpdate(planCoverableDefault=on))
    assert out.plan_coverable_default is on


async def test_a_new_expense_line_starts_deckungsfaehig_when_the_budget_says_so(
    session: AsyncSession,
) -> None:
    """§F/finance/budget/000874: a new line below an expense Titel starts with the Vermerk."""
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    plain = await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(5)))
    assert _coverable(plain)[t.exp_a.id] is False
    await _default_on(t)
    named = await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(5), coverable=False))
    assert _coverable(named)[t.exp_b.id] is False
    await t.svc.delete_line(vid, t.exp_b.id)
    again = await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(5)))
    assert _coverable(again)[t.exp_b.id] is True
    income = await t.svc.create_plan_node(
        vid, PlanNodeCreate(parentId=t.inc.id, key="9", name="Spenden", amount=D(1))
    )
    new = next(x for x in _version(income).lines if x.budget_id not in _coverable(again))
    assert new.coverable is False
    off = await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(coverable=False))
    kept = await t.svc.set_line(vid, t.exp_b.id, PlanLineSet(amount=D(7)))
    assert _coverable(off)[t.exp_b.id] is False
    assert _coverable(kept)[t.exp_b.id] is False


async def test_the_lines_of_a_titel_start_deckungsfaehig_when_it_becomes_expense(
    session: AsyncSession,
) -> None:
    """§F/finance/budget/000874: the Titel and each line below it get the Vermerk."""
    t = await _tree(session)
    await _default_on(t)
    vid = _version(await _draft(t, sides=False)).id
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(5)))
    before = await t.svc.set_line(vid, t.inc.id, PlanLineSet(side="income"))
    assert not any(_coverable(before).values())
    after = await t.svc.set_line(vid, t.exp.id, PlanLineSet(side="expense"))
    assert _coverable(after) == {t.exp_a.id: True, t.inc.id: False, t.exp.id: True}
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(coverable=False))
    same = await t.svc.set_line(vid, t.exp.id, PlanLineSet(side="expense"))
    assert _coverable(same)[t.exp_a.id] is False
    await t.svc.set_line(vid, t.exp.id, PlanLineSet(side="income"))
    back = await t.svc.set_line(vid, t.exp.id, PlanLineSet(side="expense", coverable=False))
    assert _coverable(back) == {t.exp_a.id: True, t.inc.id: False, t.exp.id: False}


async def test_the_default_changes_no_line_that_exists(session: AsyncSession) -> None:
    """§F/finance/budget/000874: the setting and a copy leave the lines as they are."""
    t = await _tree(session)
    plan = await _balanced_draft(t)
    vid = _version(plan).id
    await _default_on(t)
    assert not any(_coverable(await t.svc.get_plan(t.top.id, t.fy.id)).values())
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(coverable=True))
    await _default_on(t, on=False)
    assert _coverable(await t.svc.get_plan(t.top.id, t.fy.id))[t.exp_a.id] is True
    await _default_on(t)
    await t.svc.set_plan_state(vid, PlanStateSet(state="in_force"))
    await session.commit()
    nachtrag = await t.svc.create_nachtrag(t.top.id, t.fy.id)
    assert _coverable(nachtrag) == {
        t.inc.id: False, t.exp.id: False, t.exp_a.id: True, t.exp_b.id: False,
    }


async def test_a_version_exports_with_the_year_before_and_the_version_before(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The export holds the lines, the year before and, for a Nachtrag, the version before.

    Rule: §F/finance/budget/000875.
    """
    today = date(2026, 11, 13)
    t = await _tree(session)
    plan = await _in_force(t)
    await t.svc.book_expense(
        ExpenseCreate(budgetId=t.exp_a.id, fiscalYearId=t.fy.id, amount=D(25), description="x"),
        actor="tester",
    )
    first = await t.svc.plan_export(_version(plan).id, today)
    assert (first.head.title, first.head.state, first.head.prev_year) == (
        "Haushaltsplan VS-Mittel 2026", "in_force", None,
    )
    assert first.head.exported_on == today
    assert [(g.group, g.amount) for g in first.groups] == [("income", D(100)), ("expense", D(100))]
    assert [(r.key.split("-", 1)[1], r.name, r.depth, r.amount) for r in first.groups[1].rows] == [
        ("8", "Zuschüsse", 0, D(100)),
        ("8-1", "Fachschaften", 1, D(60)),
        ("8-2", "AKs", 1, D(40)),
    ]
    assert first.balance == D(0)

    nachtrag = _version(await t.svc.create_nachtrag(t.top.id, t.fy.id))
    await t.svc.set_line(nachtrag.id, t.inc.id, PlanLineSet(amount=D(120)))
    await t.svc.set_line(nachtrag.id, t.exp_a.id, PlanLineSet(amount=D(80)))
    second = await t.svc.plan_export(nachtrag.id, today)
    assert (second.head.version, second.head.mark, second.nachtrag) == (
        "Nachtrag 1", "Entwurf", True,
    )
    assert [(r.amount, r.base, r.change) for r in second.groups[1].rows] == [
        (D(120), D(100), D(20)), (D(80), D(60), D(20)), (D(40), D(40), D(0)),
    ]

    nxt = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2027))
    await session.commit()
    draft = _version(await t.svc.get_plan(t.top.id, nxt.id))
    await _sided(t, draft.id)
    await t.svc.set_line(draft.id, t.exp_a.id, PlanLineSet(amount=D(70)))
    third = await t.svc.plan_export(draft.id, today)
    assert (third.head.fiscal_year, third.head.prev_year) == ("2027", "2026")
    rows = {r.name: (r.amount, r.prev, r.actual) for g in third.groups for r in g.rows}
    assert rows["Fachschaften"] == (D(70), D(60), D(25))
    assert rows["Beiträge"] == (D(100), D(100), D(0))
    assert (first.head.step, third.head.step) == (None, None)

    await _steps(t, "Beschluss", "Genehmigung")
    await t.svc.set_line(draft.id, t.exp_a.id, PlanLineSet(amount=D(60)))
    await t.svc.pass_next_step(draft.id)
    waits = await t.svc.plan_export(draft.id, today)
    assert (waits.head.state, waits.head.mark) == ("in_progress", "Genehmigung")

    with pytest.raises(NotFoundError):
        await t.svc.plan_export(uuid.uuid4(), today)

    async def no_tree() -> list[BudgetTreeNodeOut]:
        return []

    monkeypatch.setattr(t.svc, "get_tree", no_tree)
    with pytest.raises(NotFoundError):
        await t.svc.plan_export(draft.id, today)


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
    assert node.path_key.endswith("-8-3")
    assert next(x for x in _version(out).lines if x.budget_id == node.id).side == "expense"
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


async def test_a_year_with_a_plan_in_force_refuses_a_direct_allocation(
    session: AsyncSession,
) -> None:
    """A year takes an allocation by hand until a version of its plan is in force.

    Rules: §F/finance/budget/000798, §F/finance/budget/000854.
    """
    t = await _tree(session)
    by_hand = await t.svc.set_allocation(t.top.id, t.fy.id, AllocationSet(allocated=D(5)))
    assert by_hand.allocated == D(5)
    await session.commit()
    await _in_force(t)
    with pytest.raises(ConflictError) as exc:
        await t.svc.set_allocation(t.exp.id, t.fy.id, AllocationSet(allocated=D(5)))
    assert _code(exc) == "allocation_from_plan"
    nxt = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2027))
    out = await t.svc.set_allocation(t.top.id, nxt.id, AllocationSet(allocated=D(5)))
    assert out.allocated == D(5)


async def test_revert_of_a_first_allocation_respects_the_plan(session: AsyncSession) -> None:
    """The revert of an allocation in a year with a plan in force answers 409 allocation_from_plan.

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
    vid = _version(await t.svc.get_plan(t.top.id, t.fy.id)).id
    await _sided(t, vid)
    await t.svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(5)))
    await t.svc.set_plan_state(vid, PlanStateSet(state="in_force"))
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
        "budget_plan_line_set",
        "budget_plan_line_set",
        "budget_plan_state",
    ]
    assert {r.actor for r in rows} == {"tester"}
    assert rows[0].data["number"] == 0
    assert (rows[1].data["side"], rows[1].data["previousSide"]) == ("income", None)
    assert rows[4].data["raised"] == {str(t.exp.id): "60.00"}
    assert rows[4].data["blocked"] == "0.00"
    assert rows[-1].data["allocations"][str(t.top.id)] == ["0.00", "100.00"]
    assert (rows[-1].data["before"], rows[-1].data["after"]) == ("draft", "in_force")
    assert rows[-1].data["versionId"] == str(plan.versions[0].id)


async def test_the_export_logo_comes_from_the_active_branding(session: AsyncSession) -> None:
    """The export reads the export logo of the active site config, and nothing else.

    Rule: §F/administration/admin/000891.
    """
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    logo = {
        "url": "data:image/png;base64," + base64.b64encode(png).decode(),
        "filename": "logo.png",
        "mime": "image/png",
        "size": len(png),
    }
    active = (
        await session.scalars(select(SiteConfigVersion).where(SiteConfigVersion.active.is_(True)))
    ).one()
    kept = dict(active.branding)
    try:
        active.branding = {**kept, "logos": {}}
        await session.commit()
        assert await active_export_logo(session) is None
        active.branding = {**kept, "logos": {"export": logo}}
        await session.commit()
        assert await active_export_logo(session) == ExportLogo("export-logo.png", png)
    finally:
        active.branding = kept
        await session.commit()


async def _gremium(session: AsyncSession) -> uuid.UUID:
    gremium = Gremium(id=uuid.uuid4(), slug=f"g{uuid.uuid4().hex[:8]}", name="StuPa")
    session.add(gremium)
    await session.commit()
    return gremium.id


_MOTION = {
    "options": ["yes", "no", "abstain"],
    "majorityRule": "simple",
    "secret": True,
    "tieBreak": "rejected",
}


async def _prepare(
    session: AsyncSession, vid: uuid.UUID, gremium: uuid.UUID, *, status: str = "live"
) -> uuid.UUID:
    """Put the plan on the agenda of a meeting of the Gremium and prepare its vote."""
    meeting = Meeting(id=uuid.uuid4(), gremium_id=gremium, title="Sitzung", status=status)
    session.add(meeting)
    await session.flush()
    item = MeetingAgendaItem(
        id=uuid.uuid4(), meeting_id=meeting.id, plan_version_id=vid, title="Haushaltsplan"
    )
    session.add(item)
    await session.commit()
    vote = await VotingService(session).create_internal(
        None,
        VoteCreateInternal(
            config=VoteConfig.model_validate(_MOTION),
            eligibleGroup=gremium,
            question="Haushaltsplan",
            eligibleCount=1,
            planVersionId=vid,
        ),
        meeting_id=meeting.id,
        agenda_item_id=item.id,
        planned_ok=True,
        actor="mgr",
    )
    return vote.id


async def _ask(session: AsyncSession, t: Tree, vid: uuid.UUID, gremium: uuid.UUID) -> uuid.UUID:
    """Ask for the decision of the next step and prepare its vote in a live meeting."""
    await t.svc.request_step(vid)
    await session.commit()
    return await _prepare(session, vid, gremium)


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


async def test_the_open_of_a_vote_keeps_the_file_of_the_plan(session: AsyncSession) -> None:
    """The protocol gets the plan as the vote saw it, also after a change or a delete.

    Rule: §F/finance/budget/000876.
    """
    today = date(2026, 11, 13)
    t = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id
    live = await t.svc.plan_file_for_protocol(vid, (), today)
    assert live is not None
    assert (live.name, live.config["plan"]["mark"]) == (  # type: ignore[index]
        "Haushaltsplan_VS-Mittel_2026_Entwurf.pdf", "Entwurf",
    )
    assert await t.svc.plan_file_for_protocol(None, (), today) is None

    vote_id = await _ask(session, t, vid, gremium)
    await _decide(session, vote_id, gremium, "no")
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D("11.11")))
    await session.commit()
    kept = await t.svc.plan_file_for_protocol(vid, (vote_id, uuid.uuid4()), today)
    now = await t.svc.plan_file_for_protocol(vid, (), today)
    assert kept is not None and now is not None
    assert kept.name == "Haushaltsplan_VS-Mittel_2026.pdf"
    assert "60,00" in str(kept.config) and "11,11" not in str(kept.config)
    assert "Beschluss" in str(kept.config["plan"])
    assert "11,11" in str(now.config)
    assert kept.source.startswith("---")

    await t.svc.keep_vote_snapshot(vid, vote_id, today)
    await session.commit()
    again = await t.svc.plan_file_for_protocol(vid, (vote_id,), today)
    assert again is not None and "11,11" in str(again.config)
    gone = await t.svc.plan_file_for_protocol(None, (vote_id,), today)
    assert gone is not None and gone.name == again.name


async def test_a_reader_gets_the_drafts_for_a_reading(session: AsyncSession) -> None:
    """An agenda offers the drafts that its Gremium decides and that the person can read.

    Rule: §F/finance/budget/000876.
    """
    t = await _tree(session)
    other = await _tree(session)
    foreign = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", gremium_id=gremium)
    await _steps(other, "Beschluss", gremium_id=gremium)
    top = await session.get(Budget, t.top.id)
    assert top is not None
    top.view_gremium_id = gremium
    await session.commit()
    vid = _version(await t.svc.get_plan(t.top.id, t.fy.id)).id
    other_vid = _version(await other.svc.get_plan(other.top.id, other.fy.id)).id
    foreign_vid = _version(await foreign.svc.get_plan(foreign.top.id, foreign.fy.id)).id

    assert await t.svc.plan_budget_ids(gremium) == {t.top.id, other.top.id}
    assert await t.svc.plan_budget_ids(uuid.uuid4()) == frozenset()
    every = {p.plan_version_id: p for p in await t.svc.reading_plans(gremium, None)}
    assert set(every) == {vid, other_vid}
    assert (every[vid].reading, every[vid].step, every[vid].title) == (
        True, "Lesung", "Haushaltsplan VS-Mittel 2026: Lesung",
    )
    assert [p.plan_version_id for p in await t.svc.reading_plans(gremium, {gremium})] == [vid]
    assert await t.svc.reading_plans(gremium, set()) == []
    assert await t.svc.reading_plans(uuid.uuid4(), None) == []

    mine = await t.svc.reading_plan(vid, gremium, {gremium})
    assert mine is not None and mine.plan_version_id == vid
    assert (await t.svc.reading_plan(other_vid, gremium, None)) is not None
    assert await t.svc.reading_plan(foreign_vid, gremium, None) is None
    with pytest.raises(ForbiddenError):
        await t.svc.reading_plan(other_vid, gremium, {gremium})
    forced = _version(await _in_force(foreign)).id
    assert await t.svc.reading_plan(forced, gremium, None) is None
    assert await t.svc.reading_plan(uuid.uuid4(), gremium, None) is None


async def test_a_step_waits_for_its_gremium_after_the_request(session: AsyncSession) -> None:
    """The request creates no vote, and the plan then waits for a meeting of the Gremium.

    Rules: §F/finance/budget/000838, §F/finance/budget/000802.
    """
    t = await _tree(session)
    gremium, other = await _gremium(session), await _gremium(session)
    await _steps(t, "Beschluss", "Genehmigung", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id
    with pytest.raises(ConflictError) as draft:
        await t.svc.waiting_plan(vid, gremium)
    assert _code(draft) == "plan_step_not_waiting"
    assert await t.svc.waiting_plans(gremium) == []

    asked = _version(await t.svc.request_step(vid))
    await session.commit()
    step = asked.steps[0]
    assert (asked.state, step.passed_at, step.vote_id) == ("in_progress", None, None)
    assert step.requested_at is not None
    assert (await session.scalars(select(Vote).where(Vote.plan_version_id == vid))).all() == []
    with pytest.raises(ConflictError) as twice:
        await t.svc.request_step(vid)
    assert _code(twice) == "plan_step_waits"
    await session.rollback()

    (waiting,) = await t.svc.waiting_plans(gremium)
    assert waiting == await t.svc.waiting_plan(vid, gremium)
    assert (waiting.plan_version_id, waiting.budget_name) == (vid, "VS-Mittel")
    assert (waiting.fiscal_year, waiting.number, waiting.step) == ("2026", 0, "Beschluss")
    assert waiting.title == "Haushaltsplan VS-Mittel 2026: Beschluss"
    assert await t.svc.waiting_plans(other) == []
    with pytest.raises(ConflictError) as foreign:
        await t.svc.waiting_plan(vid, other)
    assert _code(foreign) == "plan_step_not_waiting"
    with pytest.raises(NotFoundError):
        await t.svc.waiting_plan(uuid.uuid4(), gremium)
    await session.rollback()

    entry = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_PLAN_STEP_REQUEST)
            .where(AuditEntry.data["versionId"].astext == str(vid))
        )
    ).one()
    assert (entry.data["budget"], entry.data["year"]) == (t.top.path_key, 2026)
    assert (entry.data["step"], entry.data["gremiumId"]) == ("Beschluss", str(gremium))

    year = await session.get_one(FiscalYear, t.fy.id)
    year.closed_at = datetime.now(UTC)
    await session.commit()
    assert await t.svc.waiting_plans(gremium) == []


async def test_an_accepted_vote_of_the_gremium_passes_its_step(session: AsyncSession) -> None:
    """The vote of a meeting of the Gremium decides the step, and the accepted vote passes it.

    Rules: §F/finance/budget/000826, §F/finance/budget/000838, §F/finance/budget/000802.
    """
    t = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", "Genehmigung", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id
    vote_id = await _ask(session, t, vid, gremium)
    prepared = _version(await t.svc.get_plan(t.top.id, t.fy.id))
    assert prepared.steps[0].vote_id is None
    assert [(m.title, m.status) for m in prepared.meetings] == [("Sitzung", "live")]

    shown = await VotingService(session).get(vote_id)
    assert shown.plan_version_id == vid
    assert (await t.svc.plan_of_version(vid)).fiscal_year_id == t.fy.id
    with pytest.raises(NotFoundError):
        await t.svc.plan_of_version(uuid.uuid4())

    await _decide(session, vote_id, gremium, "yes")
    done = _version(await t.svc.get_plan(t.top.id, t.fy.id))
    assert [s.passed_at is not None for s in done.steps] == [True, False]
    assert (done.steps[0].vote_id, done.steps[0].vote_status) == (vote_id, "closed")
    assert done.steps[0].vote_result == "passed"
    entry = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_PLAN_STEP)
            .where(AuditEntry.data["versionId"].astext == str(vid))
        )
    ).one()
    assert (entry.data["voteId"], entry.actor) == (str(vote_id), "mgr")
    opened = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_PLAN_STEP_VOTE)
            .where(AuditEntry.data["versionId"].astext == str(vid))
        )
    ).one()
    assert (opened.data["voteId"], opened.actor) == (str(vote_id), "mgr")
    assert (opened.data["budget"], opened.data["year"]) == (t.top.path_key, 2026)

    with pytest.raises(ValidationProblem) as no_gremium:
        await t.svc.request_step(vid)
    assert _code(no_gremium) == "plan_step_no_gremium"


async def test_a_refused_vote_sends_the_version_back_to_the_draft(session: AsyncSession) -> None:
    """A refused vote opens each passed step again, and the version is a draft again.

    Rules: §F/finance/budget/000826, §F/finance/budget/000838.
    """
    t = await _tree(session)
    gremium = await _gremium(session)
    await t.svc.set_plan_steps(
        t.top.id,
        PlanStepsSet(
            steps=(PlanStepIn(name="Vorberatung"), PlanStepIn(name="Beschluss", gremiumId=gremium))
        ),
    )
    await session.commit()
    vid = _version(await _balanced_draft(t)).id
    await t.svc.pass_next_step(vid)
    await session.commit()
    vote_id = await _ask(session, t, vid, gremium)
    beside = await _prepare(session, vid, gremium, status="planned")
    await _decide(session, vote_id, gremium, "no")

    refused = _version(await t.svc.get_plan(t.top.id, t.fy.id))
    assert refused.state == "draft"
    assert [(s.passed_at, s.requested_at, s.vote_id) for s in refused.steps] == [
        (None, None, None),
        (None, None, None),
    ]
    assert len(refused.meetings) == 2
    closed = await session.get_one(Vote, vote_id)
    assert (closed.status, closed.result) == ("closed", "rejected")
    assert await session.get(Vote, beside) is None
    entry = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_PLAN_STATE)
            .where(AuditEntry.data["versionId"].astext == str(vid))
        )
    ).one()
    assert (entry.data["before"], entry.data["after"]) == ("in_progress", "draft")
    assert (entry.data["voteId"], entry.actor) == (str(vote_id), "mgr")
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(60), note="neu"))
    await session.commit()


async def test_a_plan_vote_opens_only_while_its_step_waits(session: AsyncSession) -> None:
    """The open of a plan vote needs a meeting and a step that waits for its Gremium.

    Rule: §F/finance/budget/000838.
    """
    t = await _tree(session)
    gremium, other = await _gremium(session), await _gremium(session)
    await _steps(t, "Beschluss", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id
    voting = VotingService(session)
    now = datetime.now(UTC)

    early = await _prepare(session, vid, gremium)
    with pytest.raises(ConflictError) as not_asked:
        await voting.open(early, now=now, actor="mgr")
    assert _code(not_asked) == "plan_step_not_waiting"
    await session.rollback()

    await t.svc.request_step(vid)
    await session.commit()
    foreign = await _prepare(session, vid, other)
    with pytest.raises(ConflictError) as wrong:
        await voting.open(foreign, now=now, actor="mgr")
    assert _code(wrong) == "plan_step_not_waiting"
    await session.rollback()

    alone = await voting.create_internal(
        None,
        VoteCreateInternal(
            config=VoteConfig.model_validate(_MOTION),
            eligibleGroup=gremium,
            question="Haushaltsplan",
            eligibleCount=1,
            planVersionId=vid,
        ),
        actor="mgr",
    )
    with pytest.raises(ConflictError) as no_meeting:
        await voting.open(alone.id, now=now, actor="mgr")
    assert _code(no_meeting) == "plan_step_not_waiting"
    await session.rollback()

    await voting.open(early, now=now, actor="mgr")
    second = await _prepare(session, vid, gremium)
    with pytest.raises(ConflictError) as runs:
        await voting.open(second, now=now, actor="mgr")
    assert _code(runs) == "plan_step_vote_runs"
    await session.rollback()
    await voting.cancel(early, actor="mgr")
    await voting.open(second, now=now, actor="mgr")
    step = _version(await t.svc.get_plan(t.top.id, t.fy.id)).steps[0]
    assert (step.vote_id, step.vote_status) == (second, "open")


async def test_back_to_draft_ends_the_votes_of_the_version(session: AsyncSession) -> None:
    """A draft vote is deleted and an open vote is cancelled.

    Rules: §F/finance/budget/000826, §F/finance/budget/000839.
    """
    t = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id

    draft = await _ask(session, t, vid, gremium)
    await t.svc.set_plan_state(vid, PlanStateSet(state="draft"))
    await session.commit()
    assert await session.get(Vote, draft) is None
    back = _version(await t.svc.get_plan(t.top.id, t.fy.id))
    assert (back.state, back.steps[0].requested_at, back.steps[0].passed_at) == (
        "draft",
        None,
        None,
    )

    opened = await _ask(session, t, vid, gremium)
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
    vote_id = await _ask(session, t, vid, gremium)
    voting = VotingService(session)
    await voting.open(vote_id, now=datetime.now(UTC), actor="mgr")
    with pytest.raises(ConflictError) as running:
        await t.svc.pass_next_step(vid)
    assert _code(running) == "plan_step_has_vote"
    await session.rollback()
    await voting.cancel(vote_id, actor="mgr")
    passed = _version(await t.svc.pass_next_step(vid))
    assert passed.steps[0].passed_at is not None


async def test_a_step_of_a_deleted_gremium_takes_no_request(session: AsyncSession) -> None:
    """A step whose Gremium is gone answers 422 plan_step_no_gremium to a request.

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
        await t.svc.request_step(vid)
    assert _code(gone) == "plan_step_no_gremium"


async def test_a_vote_decides_only_the_step_it_belongs_to(session: AsyncSession) -> None:
    """§F/finance/budget/000826: the close of a vote never fails for the state of the plan."""
    t = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id
    assert not await t.svc.pass_step_by_vote(uuid.uuid4(), uuid.uuid4())
    assert not await t.svc.refuse_step_by_vote(uuid.uuid4(), uuid.uuid4())

    first = await _ask(session, t, vid, gremium)
    assert not await t.svc.pass_step_by_vote(vid, uuid.uuid4())
    assert not await t.svc.refuse_step_by_vote(vid, uuid.uuid4())
    await session.commit()

    with pytest.raises(ConflictError) as running:
        await t.svc.set_fiscal_year_closed(t.top.id, t.fy.id, closed=True)
    assert _code(running) == "plan_in_progress"
    await session.rollback()
    voting = VotingService(session)
    now = datetime.now(UTC)
    await voting.open(first, now=now, actor="mgr")
    year = await session.get_one(FiscalYear, t.fy.id)
    year.closed_at = now
    await session.commit()
    assert not await t.svc.refuse_step_by_vote(vid, first)
    await session.commit()
    await voting.cast(first, Principal(sub="v1", groups={vote_group_key(gremium)}), "yes", now=now)
    await voting.close(first, Principal(sub="mgr", roles=["admin"]))
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
    assert _amounts(typed) == {other.inc.id: D(0), other.exp.id: D(5), other.exp_a.id: D(5)}


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
    await _in_force(t)
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
    await _in_force(t)
    with pytest.raises(ConflictError) as decided:
        await t.svc.delete_fiscal_year(t.top.id, t.fy.id)
    assert _code(decided) == "fiscal_year_has_plan"

    later = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2027))
    drafted = await t.svc.get_plan(t.top.id, later.id)
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
    vid = _version(await _draft(t, sides=False)).id
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

    Rules: §F/finance/budget/000801, §F/finance/budget/000853.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.set_fiscal_year_closed(t.top.id, t.fy.id, closed=True)
    with pytest.raises(ConflictError) as closed:
        await t.svc.set_line(vid, t.exp.id, PlanLineSet(side="income"))
    assert _code(closed) == "fiscal_year_closed"


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
    await _in_force(t)
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
    """A Titel that becomes income keeps no Vermerk on its lines of the draft.

    Rules: §F/finance/budget/000816, §F/finance/budget/000853.
    """
    t = await _tree(session)
    plan = await _draft(t)
    vid = _version(plan).id
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(transferable=True, coverable=True))
    await session.commit()
    with pytest.raises(ValidationProblem) as marked:
        await t.svc.set_line(vid, t.exp.id, PlanLineSet(side="income", coverable=True))
    assert _code(marked) == "plan_marks_income"
    await session.rollback()
    await t.svc.set_line(vid, t.exp.id, PlanLineSet(side="income"))
    await session.commit()
    session.expire_all()
    line = next(
        ln for ln in _version(await t.svc.get_plan(t.top.id, t.fy.id)).lines
        if ln.budget_id == t.exp_a.id
    )
    assert (line.side, line.transferable, line.coverable) == ("income", False, False)
    entry = (
        await session.scalars(
            select(AuditEntry)
            .where(
                AuditEntry.action == AuditAction.BUDGET_PLAN_LINE_SET.value,
                AuditEntry.target_id == str(plan.id),
            )
            .order_by(AuditEntry.id.desc())
        )
    ).first()
    assert entry is not None
    assert (entry.data["side"], entry.data["previousSide"]) == ("income", "expense")
    assert entry.data["clearedMarks"] == [
        {
            "budgetId": str(t.exp_a.id),
            "pathKey": t.exp_a.path_key,
            "name": "Fachschaften",
            "transferable": True,
            "coverable": True,
            "blocked": "0.00",
        }
    ]


async def test_a_decided_version_keeps_the_side_of_its_titel(session: AsyncSession) -> None:
    """A version that left the draft keeps its sides, and a Nachtrag starts with them.

    Rules: §F/finance/budget/000853, §F/finance/budget/000793.
    """
    t = await _tree(session)
    vid = _version(await _in_force(t)).id
    with pytest.raises(ConflictError) as exc:
        await t.svc.set_line(vid, t.exp.id, PlanLineSet(side="income"))
    assert _code(exc) == "plan_version_locked"
    await session.rollback()
    nachtrag = _version(await t.svc.create_nachtrag(t.top.id, t.fy.id))
    assert {line.budget_id: line.side for line in nachtrag.lines} == {
        t.inc.id: "income", t.exp.id: "expense", t.exp_a.id: "expense", t.exp_b.id: "expense",
    }
    moved = _version(await t.svc.set_line(nachtrag.id, t.exp.id, PlanLineSet(side="income")))
    assert next(x for x in moved.lines if x.budget_id == t.exp.id).side == "income"
    await session.commit()
    first = _version(await t.svc.get_plan(t.top.id, t.fy.id), 0)
    assert next(x for x in first.lines if x.budget_id == t.exp.id).side == "expense"


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
            .limit(5)
        )
    ).all()
    removed, added, _expense, _income, created = entries
    assert (created.data["budget"], created.data["year"]) == (t.top.path_key, 2026)
    await _steps(t, "Beschluss")
    await t.svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(5)))
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(5)))
    await t.svc.pass_next_step(vid)
    await t.svc.set_plan_state(vid, PlanStateSet(state="draft"))
    back, step = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action.like("budget_plan_st%"))
            .order_by(AuditEntry.id.desc())
            .limit(2)
        )
    ).all()
    assert (step.data["budget"], step.data["year"]) == (t.top.path_key, 2026)
    assert (back.data["budget"], back.data["year"]) == (t.top.path_key, 2026)
    assert (added.data["pathKey"], added.data["name"]) == (t.exp_a.path_key, "Fachschaften")
    assert (removed.data["pathKey"], removed.data["amount"]) == (t.exp_a.path_key, None)


@pytest.mark.parametrize(
    ("write", "answer"),
    [
        ("delete_node", None),
        ("close", None),
        ("reopen", None),
        ("side", None),
        ("steps", None),
        ("line", None),
        ("year", None),
        ("delete_version", None),
        ("delete_year", None),
        ("allocation", None),
        ("switch", None),
        ("nachtrag", "plan_draft_exists"),
        ("state", "plan_not_balanced"),
        ("plan", "plan_exists"),
        ("rename", None),
        ("create_node", None),
        ("create_year", None),
        ("step", "plan_no_step_left"),
        ("step_request", "plan_no_step_left"),
        ("draft", "plan_state_invalid"),
        ("plan_node", None),
        ("delete_line", None),
        ("revert", None),
    ],
)
async def test_a_write_beside_a_plan_waits_for_the_lock_of_its_budget(
    session: AsyncSession, write: str, answer: str | None
) -> None:
    """Each write that a plan depends on takes the lock of the top-level budget first.

    Two such writes at the same moment then run one after the other, and none ends in
    a deadlock or in a state that the rules forbid. A write that its rule refuses
    answers with the code of that rule after the wait.
    Rules: §F/finance/budget/000842, §F/finance/budget/000793, §F/finance/budget/000801,
    §F/finance/budget/000820.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await t.svc.update_node(t.exp_b.id, BudgetNodeUpdate(name="Arbeitskreise"))
    renamed = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_NODE_UPDATE.value)
            .where(AuditEntry.target_id == str(t.exp_b.id))
        )
    ).one()
    await session.commit()
    maker = async_sessionmaker(session.bind, expire_on_commit=False)

    async def write_in(svc: BudgetTreeService) -> None:
        match write:
            case "step":
                await svc.pass_next_step(vid)
            case "step_request":
                await svc.request_step(vid)
            case "draft":
                await svc.set_plan_state(vid, PlanStateSet(state="draft"))
            case "plan_node":
                await svc.create_plan_node(
                    vid, PlanNodeCreate(parentId=t.exp.id, key="9", name="Neu")
                )
            case "delete_line":
                await svc.delete_line(vid, t.inc.id)
            case "revert":
                await svc.revert_audit(await svc.session.get_one(AuditEntry, renamed.id), "tester")
            case "delete_node":
                await svc.delete_node(t.exp_b.id)
            case "close":
                await svc.set_fiscal_year_closed(t.top.id, t.fy.id, closed=True)
            case "reopen":
                await svc.set_fiscal_year_closed(t.top.id, t.fy.id, closed=False)
            case "side":
                await svc.set_line(vid, t.exp.id, PlanLineSet(side="expense"))
            case "steps":
                await svc.set_plan_steps(t.top.id, PlanStepsSet(steps=()))
            case "line":
                await svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(1)))
            case "year":
                await svc.update_fiscal_year(t.top.id, t.fy.id, FiscalYearUpdate(year=2031))
            case "delete_version":
                await svc.delete_version(vid)
            case "delete_year":
                await svc.delete_fiscal_year(t.top.id, t.fy.id)
            case "allocation":
                await svc.set_allocation(t.top.id, t.fy.id, AllocationSet(allocated=D(1)))
            case "switch":
                await svc.set_plan_switch(t.top.id, False)
            case "nachtrag":
                await svc.create_nachtrag(t.top.id, t.fy.id)
            case "state":
                await svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(1)))
                await svc.set_plan_state(vid, PlanStateSet(state="in_force"))
            case "plan":
                await svc.create_plan(t.top.id, t.fy.id, PlanCreate())
            case "rename":
                await svc.update_node(t.top.id, BudgetNodeUpdate(key=f"N{uuid.uuid4().hex[:8]}"))
            case "create_node":
                await svc.create_node(BudgetNodeCreate(key="9", name="Neu", parentId=t.exp.id))
            case _:
                await svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2040))

    async def run() -> str | None:
        async with maker() as other:
            try:
                await write_in(BudgetTreeService(other, actor="tester"))
            except AppError as refused:
                return refused.code
            await other.commit()
            return None

    async with maker() as holder:
        await holder.execute(
            select(Budget.id).where(Budget.id == t.top.id).with_for_update()
        )
        task = asyncio.create_task(run())
        await asyncio.sleep(0.3)
        assert not task.done()
        await holder.commit()
    assert await asyncio.wait_for(task, 10) == answer


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
    drafted = await t.svc.get_plan(t.top.id, later.id)
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
    assert off.data["deletedYears"] == [2026]


async def test_a_key_taken_at_the_same_moment_is_a_conflict(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key that another request took after the read answers 409, not a 500.

    Rules: §F/finance/budget/000246, §F/finance/budget/000817, §F/finance/budget/000842.
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


async def test_a_plan_that_went_while_a_write_waited_is_not_found(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that waited for the lock while its plan was deleted answers 404.

    Rules: §F/finance/budget/000842, §F/finance/budget/000793.
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


async def test_a_version_that_went_while_a_write_waited_is_not_found(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that waited while its draft was deleted answers 404, and so does a vote.

    Rule: §F/finance/budget/000842.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await session.commit()

    async def version_goes(_plan_id: uuid.UUID) -> None:
        await session.execute(delete(BudgetPlanVersion).where(BudgetPlanVersion.id == vid))

    monkeypatch.setattr(t.svc, "_lock_top_of_plan", version_goes)
    with pytest.raises(NotFoundError):
        await t.svc.set_line(vid, t.inc.id, PlanLineSet(amount=D(1)))
    await session.rollback()
    assert await t.svc.lock_plan_of_version(vid) is None


async def test_an_allocation_that_waited_for_the_plan_is_refused(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An allocation by hand checks the plan after it has the lock of the budget.

    The plan comes into force while the allocation waits, so the allocation reads the
    plan again and is refused: the version in force keeps the allocation it wrote.
    Rules: §F/finance/budget/000842, §F/finance/budget/000798.
    """
    t = await _tree(session)
    vid = _version(await _balanced_draft(t)).id
    lock = t.svc._lock_tree

    async def plan_comes_into_force(budget_id: uuid.UUID | None) -> None:
        async with async_sessionmaker(session.bind, expire_on_commit=False)() as other:
            await BudgetTreeService(other, actor="tester").set_plan_state(
                vid, PlanStateSet(state="in_force")
            )
            await other.commit()
        await lock(budget_id)

    monkeypatch.setattr(t.svc, "_lock_tree", plan_comes_into_force)
    with pytest.raises(ConflictError) as refused:
        await t.svc.set_allocation(t.exp_a.id, t.fy.id, AllocationSet(allocated=D(20)))
    assert _code(refused) == "allocation_from_plan"
    await session.rollback()
    assert (await _allocations(session, t))[t.exp_a.id] == D(60)


async def test_the_close_of_a_step_vote_locks_the_plan_before_the_audit_entry(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The close of a step vote holds the lock of the plan before it writes an entry.

    A plan write holds the lock of its budget and then writes its entry, so the close
    takes the same order and the two never wait for each other.
    Rule: §F/finance/budget/000842.
    """
    import app.modules.voting.service as voting

    t = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id
    vote_id = await _ask(session, t, vid, gremium)
    order: list[str] = []
    lock, record = BudgetTreeService.lock_plan_of_version, voting.audit_record

    async def locked(svc: BudgetTreeService, version_id: uuid.UUID) -> BudgetPlanVersion | None:
        order.append("lock")
        return await lock(svc, version_id)

    async def recorded(*args: object, **kwargs: object) -> object:
        order.append(str(kwargs["action"]))
        return await record(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(BudgetTreeService, "lock_plan_of_version", locked)
    monkeypatch.setattr(voting, "audit_record", recorded)
    await _decide(session, vote_id, gremium, "yes")
    assert order.index("lock") < order.index(str(AuditAction.VOTE_CLOSE))


async def test_the_audit_log_names_a_plan_and_a_budget(session: AsyncSession) -> None:
    """The audit log shows a plan as its budget and year, and a budget by its name.

    Rule: §F/finance/budget/000802.
    """
    from app.modules.audit_log.service import AuditLogService

    t = await _tree(session)
    plan = await t.svc.get_plan(t.top.id, t.fy.id)
    log = AuditLogService(session)
    labels = await log.resolve_target_labels(
        [("budget_plan", str(plan.id)), ("budget", str(t.exp_a.id))]
    )
    assert labels[("budget", str(t.exp_a.id))] == "Fachschaften"
    assert "2026" in labels[("budget_plan", str(plan.id))]
    assert "VS-Mittel" in labels[("budget_plan", str(plan.id))]
    names = await log.resolve_data_ids([{"planId": str(plan.id), "budgetId": str(t.exp_a.id)}])
    assert names[str(t.exp_a.id)] == "Fachschaften"
    assert "2026" in names[str(plan.id)]


async def test_a_kostenstelle_that_went_while_a_write_waited_is_not_found(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that waited for the lock while its Kostenstelle was deleted answers 404.

    Rule: §F/finance/budget/000842.
    """
    t = await _tree(session, enabled=False)
    lock = t.svc._lock_tree

    async def node_goes(budget_id: uuid.UUID | None) -> None:
        await lock(budget_id)
        await session.execute(delete(Budget).where(Budget.id == t.exp_b.id))

    monkeypatch.setattr(t.svc, "_lock_tree", node_goes)
    with pytest.raises(NotFoundError):
        await t.svc.update_node(t.exp_b.id, BudgetNodeUpdate(name="Weg"))
    await session.rollback()
    with pytest.raises(NotFoundError):
        await t.svc.set_allocation(t.exp_b.id, t.fy.id, AllocationSet(allocated=D(1)))
    await session.rollback()
    with pytest.raises(NotFoundError):
        await t.svc.create_node(BudgetNodeCreate(key="1", name="Kind", parentId=t.exp_b.id))


async def test_a_key_that_another_request_holds_is_a_conflict(session: AsyncSession) -> None:
    """Two top-level budgets that take one key at the same moment: one answers 409.

    Two top-level budgets share no lock of a tree. The second request waits for the
    unique index before its audit entry and then answers 409, not a 500.
    Rules: §F/finance/budget/000246, §F/finance/budget/000842.
    """
    from sqlalchemy import update

    one, two = await _tree(session, enabled=False), await _tree(session, enabled=False)
    key = f"K{uuid.uuid4().hex[:8]}"
    maker = async_sessionmaker(session.bind, expire_on_commit=False)

    async def run() -> str | None:
        async with maker() as other:
            try:
                await BudgetTreeService(other, actor="tester").update_node(
                    two.top.id, BudgetNodeUpdate(key=key)
                )
            except AppError as refused:
                return refused.code
            return None

    async with maker() as holder:
        await holder.execute(
            update(Budget).where(Budget.id == one.top.id).values(key=key, path_key=key)
        )
        task = asyncio.create_task(run())
        await asyncio.sleep(0.3)
        assert not task.done()
        await holder.commit()
    assert await asyncio.wait_for(task, 10) == "budget_key_exists"
    with pytest.raises(ValidationProblem):
        await one.svc.update_node(one.top.id, BudgetNodeUpdate(key="AB\n"))
    with pytest.raises(ValidationProblem):
        await one.svc.create_node(BudgetNodeCreate(key="AB\n", name="Zeilenende"))


async def test_the_gremium_of_the_view_must_exist(session: AsyncSession) -> None:
    """An unknown Gremium of the view answers 422, a Gremium is saved.

    Rule: §F/finance/budget/000259.
    """
    t = await _tree(session, enabled=False)
    gremium = await _gremium(session)
    saved = await t.svc.update_node(t.exp.id, BudgetNodeUpdate(viewGremiumId=gremium))
    assert saved.view_gremium_id == gremium
    with pytest.raises(ValidationProblem) as unknown:
        await t.svc.update_node(t.exp.id, BudgetNodeUpdate(viewGremiumId=uuid.uuid4()))
    assert _code(unknown) == "view_gremium_invalid"
    cleared = await t.svc.update_node(t.exp.id, BudgetNodeUpdate(viewGremiumId=None))
    assert cleared.view_gremium_id is None


async def test_a_year_changes_only_through_its_own_budget(session: AsyncSession) -> None:
    """A fiscal year reached through another budget answers 404 and stays as it is.

    Rule: §F/finance/budget/000845.
    """
    own, other = await _tree(session, enabled=False), await _tree(session, enabled=False)
    with pytest.raises(NotFoundError):
        await other.svc.update_fiscal_year(other.top.id, own.fy.id, FiscalYearUpdate(year=2040))
    with pytest.raises(NotFoundError):
        await other.svc.update_fiscal_year(
            other.top.id, own.fy.id, FiscalYearUpdate(active=False)
        )
    with pytest.raises(NotFoundError):
        await other.svc.set_fiscal_year_closed(other.top.id, own.fy.id, closed=True)
    with pytest.raises(NotFoundError):
        await other.svc.delete_fiscal_year(other.top.id, own.fy.id)
    await session.rollback()
    year = await session.get_one(FiscalYear, own.fy.id)
    await session.refresh(year)
    assert (year.year, year.active, year.closed_at) == (2026, own.fy.active, None)


async def test_a_gremium_with_a_budget_is_not_deleted(session: AsyncSession) -> None:
    """The delete of a Gremium with a budget answers 409, and the budget and its plan stay.

    Rule: §F/finance/budget/000844.
    """
    from app.modules.admin.service import ConfigService

    gremium = await _gremium(session)
    svc = BudgetTreeService(session, actor="tester")
    top = await svc.create_node(
        BudgetNodeCreate(key=f"G{uuid.uuid4().hex[:8]}", name="Gremium", gremiumId=gremium)
    )
    exp = await svc.create_node(BudgetNodeCreate(key="8", name="Ausgaben", parentId=top.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    await svc.set_plan_switch(top.id, True)
    await session.commit()
    admin = Principal(sub="admin", roles=["admin"])
    with pytest.raises(ConflictError) as refused:
        await ConfigService(session).delete_gremium(gremium, admin)
    assert _code(refused) == "gremium_has_budget"
    await session.rollback()
    assert (await svc.get_plan(top.id, fy.id)).fiscal_year_id == fy.id
    assert await session.get(Budget, exp.id) is not None
    await session.execute(delete(Budget).where(Budget.id == exp.id))
    await session.execute(delete(Budget).where(Budget.id == top.id))
    await session.commit()
    await ConfigService(session).delete_gremium(gremium, admin)
    assert await session.get(Gremium, gremium) is None


@pytest.mark.parametrize("field", ["viewGremiumId", "decisionGremiumId"])
async def test_a_gremium_that_went_while_a_write_waited_is_not_valid(
    session: AsyncSession, field: str
) -> None:
    """A write that names a Gremium beside the delete of that Gremium answers 422.

    The write waits for the delete and then reads that the Gremium is gone. Without the
    wait the write passes its check and breaks the foreign key at its flush.
    Rule: §F/finance/budget/000842.
    """
    t = await _tree(session, enabled=False)
    gremium = await _gremium(session)
    maker = async_sessionmaker(session.bind, expire_on_commit=False)

    async def run() -> str:
        async with maker() as other:
            svc = BudgetTreeService(other, actor="tester")
            try:
                await svc.update_node(t.exp.id, BudgetNodeUpdate.model_validate({field: gremium}))
            except ValidationProblem as exc:
                return exc.code
            return "saved"

    async with maker() as holder:
        await holder.execute(delete(Gremium).where(Gremium.id == gremium))
        task = asyncio.create_task(run())
        await asyncio.sleep(0.3)
        assert not task.done()
        await holder.commit()
    code = "view_gremium_invalid" if field == "viewGremiumId" else "decision_gremium_invalid"
    assert await asyncio.wait_for(task, 10) == code


async def test_a_budget_for_a_gremium_that_goes_beside_the_create_is_not_found(
    session: AsyncSession,
) -> None:
    """The create of a budget beside the delete of its Gremium answers 404.

    Rule: §F/finance/budget/000842.
    """
    gremium = await _gremium(session)
    maker = async_sessionmaker(session.bind, expire_on_commit=False)

    async def run() -> str:
        async with maker() as other:
            node = BudgetNodeCreate(key=f"N{uuid.uuid4().hex[:8]}", name="Neu", gremiumId=gremium)
            try:
                await BudgetTreeService(other, actor="tester").create_node(node)
            except NotFoundError:
                return "not found"
            return "saved"

    async with maker() as holder:
        await holder.execute(delete(Gremium).where(Gremium.id == gremium))
        task = asyncio.create_task(run())
        await asyncio.sleep(0.3)
        assert not task.done()
        await holder.commit()
    assert await asyncio.wait_for(task, 10) == "not found"


async def test_only_a_taken_key_is_a_key_conflict(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another error of the write of a key stays an error and is no 409 for the key.

    A Gremium that goes away between its check and the write breaks a foreign key. The
    key is free then, so the answer must not name the key.
    Rule: §F/finance/budget/000246.
    """
    from sqlalchemy.exc import IntegrityError

    t = await _tree(session, enabled=False)

    async def unchecked(_gremium: object, _field: str) -> None:
        return None

    monkeypatch.setattr(t.svc, "_check_gremium", unchecked)
    with pytest.raises(IntegrityError):
        await t.svc.update_node(
            t.exp.id, BudgetNodeUpdate(key="77", viewGremiumId=uuid.uuid4())
        )
    await session.rollback()
    with pytest.raises(IntegrityError):
        await t.svc.create_node(
            BudgetNodeCreate(
                key="78", name="Neu", parentId=t.exp.id, decisionGremiumId=uuid.uuid4()
            )
        )
    await session.rollback()


@pytest.mark.parametrize("write", ["rename", "create"])
async def test_a_top_level_key_waits_for_the_lock_of_the_top_level_keys(
    session: AsyncSession, write: str
) -> None:
    """A top-level budget takes the lock of the top-level keys before it writes its key.

    Two budgets with Kostenstellen that take one key at the same moment would else
    each write a part of the path keys and wait for the other.
    Rules: §F/finance/budget/000246, §F/finance/budget/000842.
    """
    from sqlalchemy import func

    from app.modules.budget.tree.nodes import _TOP_KEYS_LOCK

    t = await _tree(session, enabled=False)
    key = f"L{uuid.uuid4().hex[:8]}"
    maker = async_sessionmaker(session.bind, expire_on_commit=False)

    async def run() -> str:
        async with maker() as other:
            svc = BudgetTreeService(other, actor="tester")
            if write == "rename":
                return (await svc.update_node(t.top.id, BudgetNodeUpdate(key=key))).path_key
            return (await svc.create_node(BudgetNodeCreate(key=key, name="Neu"))).path_key

    async with maker() as holder:
        await holder.execute(select(func.pg_advisory_xact_lock(_TOP_KEYS_LOCK)))
        task = asyncio.create_task(run())
        await asyncio.sleep(0.3)
        assert not task.done()
        await holder.commit()
    assert await asyncio.wait_for(task, 10) == key


async def test_the_read_of_a_version_beside_its_delete_is_no_error(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A delete that takes the version away during the read of its plan gives no error.

    Rule: §F/finance/budget/000838.
    """
    t = await _tree(session)
    vid = _version(await _draft(t)).id
    await session.commit()
    maker = async_sessionmaker(session.bind, expire_on_commit=False)
    read = t.svc._get_fiscal_year

    async def gone(fiscal_year_id: uuid.UUID) -> FiscalYear:
        async with maker() as other:
            await BudgetTreeService(other, actor="tester").delete_version(vid)
            await other.commit()
        return await read(fiscal_year_id)

    monkeypatch.setattr(t.svc, "_get_fiscal_year", gone)
    shown = await t.svc.plan_of_version(vid)
    assert shown.fiscal_year_id == t.fy.id
    assert vid not in [version.id for version in shown.versions]


def _by_hand(state: str, step: int | None = None) -> PlanStateByHand:
    return PlanStateByHand.model_validate({"state": state, "step": step, "reason": "Altbestand"})


async def test_a_state_by_hand_moves_forwards_and_backwards(session: AsyncSession) -> None:
    """The newest version takes the draft, each step and the state in force by hand.

    The steps before the chosen state are passed by hand, the steps after it are open,
    and a version that leaves the state in force keeps the allocations.
    Rules: §F/finance/budget/000855, §F/finance/budget/000802.
    """
    t = await _tree(session)
    await _steps(t, "Beschluss", "Genehmigung")
    plan = await _balanced_draft(t)
    vid = _version(plan).id

    second = _version(await t.svc.set_state_by_hand(vid, _by_hand("in_progress", 1)))
    assert second.state == "in_progress"
    assert [(s.name, s.passed_at is not None, s.by_hand) for s in second.steps] == [
        ("Beschluss", True, True),
        ("Genehmigung", False, False),
    ]
    assert await _allocations(session, t) == {}
    await session.commit()
    with pytest.raises(ConflictError) as same:
        await t.svc.set_state_by_hand(vid, _by_hand("in_progress", 1))
    assert _code(same) == "plan_state_invalid"
    await session.rollback()

    first = _version(await t.svc.set_state_by_hand(vid, _by_hand("in_progress", 0)))
    assert [(s.passed_at, s.by_hand) for s in first.steps] == [(None, False), (None, False)]

    force = _version(await t.svc.set_state_by_hand(vid, _by_hand("in_force")))
    assert (force.state, force.in_force_at is not None) == ("in_force", True)
    assert [s.by_hand for s in force.steps] == [True, True]
    await session.commit()
    written = await _allocations(session, t)
    assert written[t.exp_a.id] == D(60)
    with pytest.raises(ConflictError) as again:
        await t.svc.set_state_by_hand(vid, _by_hand("in_force"))
    assert _code(again) == "plan_state_invalid"
    await session.rollback()

    back = _version(await t.svc.set_state_by_hand(vid, _by_hand("in_progress", 1)))
    assert (back.state, back.in_force_at) == ("in_progress", None)
    assert [s.passed_at is not None for s in back.steps] == [True, False]
    draft = _version(await t.svc.set_state_by_hand(vid, _by_hand("draft")))
    assert (draft.state, draft.in_force_at) == ("draft", None)
    assert [(s.passed_at, s.by_hand) for s in draft.steps] == [(None, False), (None, False)]
    assert {(line.name, line.path_key) for line in draft.lines} == {(None, None)}
    assert await _allocations(session, t) == written
    await session.commit()
    with pytest.raises(ConflictError) as drafted:
        await t.svc.set_state_by_hand(vid, _by_hand("draft"))
    assert _code(drafted) == "plan_state_invalid"
    await session.rollback()

    rows = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_PLAN_STATE_SET.value)
            .where(AuditEntry.target_id == str(plan.id))
            .order_by(AuditEntry.id)
        )
    ).all()
    assert [(r.data["before"], r.data["after"], r.data["step"]) for r in rows] == [
        ("draft", "in_progress", "Genehmigung"),
        ("in_progress", "in_progress", "Beschluss"),
        ("in_progress", "in_force", None),
        ("in_force", "in_progress", "Genehmigung"),
        ("in_progress", "draft", None),
    ]
    assert {(r.actor, r.data["reason"], r.data["versionId"]) for r in rows} == {
        ("tester", "Altbestand", str(vid))
    }
    assert rows[2].data["allocations"][str(t.top.id)] == ["0.00", "100.00"]
    assert rows[3].data["allocations"] == {}


async def test_a_state_by_hand_checks_the_step_and_the_draft(session: AsyncSession) -> None:
    """A wrong step answers 422, and a draft leaves the draft only with its checks.

    Rules: §F/finance/budget/000855, §F/finance/budget/000853, §F/finance/budget/000801.
    """
    t = await _tree(session)
    await _steps(t, "Beschluss")
    vid = _version(await _draft(t, sides=False)).id
    for state, step in (("in_progress", None), ("in_progress", 1), ("draft", 0), ("in_force", 0)):
        with pytest.raises(ValidationProblem) as wrong:
            await t.svc.set_state_by_hand(vid, _by_hand(state, step))
        assert _code(wrong) == "plan_step_invalid"
        await session.rollback()
    with pytest.raises(ValidationProblem) as empty:
        await t.svc.set_state_by_hand(vid, _by_hand("in_force"))
    assert _code(empty) == "plan_empty"
    await session.rollback()
    await t.svc.set_line(vid, t.exp_a.id, PlanLineSet(amount=D(0)))
    await session.commit()
    with pytest.raises(ValidationProblem) as sides:
        await t.svc.set_state_by_hand(vid, _by_hand("in_progress", 0))
    assert _code(sides) == "plan_side_missing"
    await session.rollback()
    with pytest.raises(NotFoundError):
        await t.svc.set_state_by_hand(uuid.uuid4(), _by_hand("draft"))
    await t.svc.set_fiscal_year_closed(t.top.id, t.fy.id, closed=True)
    with pytest.raises(ConflictError) as closed:
        await t.svc.set_state_by_hand(vid, _by_hand("in_force"))
    assert _code(closed) == "fiscal_year_closed"


async def test_only_the_newest_version_takes_a_state_by_hand(session: AsyncSession) -> None:
    """An older version keeps its state, and the newest one replaces the version in force.

    Rules: §F/finance/budget/000855, §F/finance/budget/000792.
    """
    t = await _tree(session)
    stamm = _version(await _in_force(t))
    nachtrag = _version(await t.svc.create_nachtrag(t.top.id, t.fy.id))
    await session.commit()
    with pytest.raises(ConflictError) as older:
        await t.svc.set_state_by_hand(stamm.id, _by_hand("draft"))
    assert _code(older) == "plan_state_invalid"
    await session.rollback()
    plan = await t.svc.set_state_by_hand(nachtrag.id, _by_hand("in_force"))
    assert [v.state for v in plan.versions] == ["replaced", "in_force"]


async def test_a_state_by_hand_ends_the_open_vote_of_the_version(session: AsyncSession) -> None:
    """The vote of a step does not stay open when the state changes by hand.

    Rules: §F/finance/budget/000855, §F/finance/budget/000838.
    """
    t = await _tree(session)
    gremium = await _gremium(session)
    await _steps(t, "Beschluss", gremium_id=gremium)
    vid = _version(await _balanced_draft(t)).id
    vote_id = await _ask(session, t, vid, gremium)
    await VotingService(session).open(vote_id, now=datetime.now(UTC), actor="mgr")
    await session.commit()
    done = _version(await t.svc.set_state_by_hand(vid, _by_hand("in_force")))
    await session.commit()
    assert done.state == "in_force"
    vote = await session.get_one(Vote, vote_id)
    await session.refresh(vote)
    assert vote.status == "cancelled"


async def test_a_new_fiscal_year_gets_a_draft(session: AsyncSession) -> None:
    """A later year gets a draft, as a copy of the latest plan in force before it.

    Rules: §F/finance/budget/000854, §F/finance/budget/000837.
    """
    off = await _tree(session, enabled=False)
    plain = await off.svc.create_fiscal_year(off.top.id, FiscalYearCreate(year=2027))
    assert not await off.svc.plan_exists(plain.id)

    t = await _tree(session)
    before = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2025))
    empty = _version(await t.svc.get_plan(t.top.id, before.id))
    assert (empty.number, empty.state) == (0, "draft")
    assert {(line.amount, line.side) for line in empty.lines} == {(D(0), None)}
    assert len(empty.lines) == 4

    await _in_force(t)
    nxt = await t.svc.create_fiscal_year(t.top.id, FiscalYearCreate(year=2027))
    plan = await t.svc.get_plan(t.top.id, nxt.id)
    copy = _version(plan)
    assert (copy.number, copy.state, len(plan.versions)) == (0, "draft", 1)
    assert {line.budget_id: (line.side, line.amount) for line in copy.lines} == {
        t.inc.id: ("income", D(100)),
        t.exp.id: ("expense", D(100)),
        t.exp_a.id: ("expense", D(60)),
        t.exp_b.id: ("expense", D(40)),
    }
    assert await _allocated(session, nxt.id) == {}
    entry = (
        await session.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.BUDGET_PLAN_VERSION_CREATE.value)
            .where(AuditEntry.target_id == str(plan.id))
        )
    ).one()
    assert entry.data["copiedFromFiscalYearId"] == str(t.fy.id)
