"""Haushaltsplan: side, plan switch, versions, lines and state changes.

The decisions live in `app.modules.budget.plan_rules`. The methods here read the
rows, ask the rules and write the result. They do not commit: the router commits
after the method returns, so a refused request leaves no row. `create_step_vote` is the
exception, because the voting service commits the vote it creates.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, assert_never, cast
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.modules.audit.actions import AuditAction
from app.modules.budget import plan_rules, tree_rules
from app.modules.budget.plan_models import (
    BudgetPlan,
    BudgetPlanLine,
    BudgetPlanStep,
    BudgetPlanVersion,
)
from app.modules.budget.plan_rules import PlanState, PlanTarget, Side
from app.modules.budget.plan_schemas import (
    PlanCreate,
    PlanLineOut,
    PlanLineSet,
    PlanNodeCreate,
    PlanOut,
    PlanStateSet,
    PlanStepOut,
    PlanStepsOut,
    PlanStepsSet,
    PlanSwitchChange,
    PlanSwitchOut,
    PlanSwitchPreview,
    PlanVersionOut,
    SideOut,
)
from app.modules.budget.tree.allocations import AllocationOps
from app.modules.budget.tree.nodes import NodeOps
from app.modules.budget.tree.service_base import _ZERO
from app.modules.budget.tree_models import Budget, BudgetAllocation, FiscalYear
from app.modules.gremien.models import Gremium
from app.modules.meetings.rules import MeetingRules
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteCreateInternal
from app.modules.voting.service import VotingService
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

_CENT = Decimal("0.01")


def _changes_out(changes: dict[UUID, tuple[Decimal, Decimal]]) -> dict[str, list[str]]:
    """Return allocation changes as audit data: `[before, after]` per cost center."""
    return {
        str(node): [f"{before:.2f}", f"{after:.2f}"] for node, (before, after) in changes.items()
    }


def _line_out(line: BudgetPlanLine) -> PlanLineOut:
    return PlanLineOut(
        budgetId=line.budget_id,
        amount=line.amount.quantize(_CENT),
        note=line.note,
        name=line.name,
        pathKey=line.path_key,
        transferable=bool(line.transferable),
        coverable=bool(line.coverable),
        blocked=(line.blocked if line.blocked is not None else _ZERO).quantize(_CENT),
    )


class PlanOps(NodeOps, AllocationOps):
    """Read and write the Haushaltsplan of a fiscal year."""

    async def _plan_of(self, fiscal_year_id: UUID) -> BudgetPlan | None:
        return (
            await self.session.scalars(
                select(BudgetPlan).where(BudgetPlan.fiscal_year_id == fiscal_year_id)
            )
        ).one_or_none()

    async def _versions(self, plan_id: UUID) -> list[BudgetPlanVersion]:
        return list(
            (
                await self.session.scalars(
                    select(BudgetPlanVersion)
                    .where(BudgetPlanVersion.plan_id == plan_id)
                    .order_by(BudgetPlanVersion.number)
                )
            ).all()
        )

    async def _plan_year(self, budget_id: UUID, fiscal_year_id: UUID) -> tuple[Budget, FiscalYear]:
        """Return the top-level node and its fiscal year for a plan route.

        Raises:
            NotFoundError: The node or the fiscal year does not exist, or the fiscal
                year belongs to a different top-level node (404).
            ValidationProblem: `plan_top_level_only` (422) for a node below the top
                level.
        """
        top = await self._get_node(budget_id)
        if top.parent_id is not None:
            raise ValidationProblem(
                "A Haushaltsplan belongs to a top-level cost centre.",
                code="plan_top_level_only",
                errors=[{"field": "budgetId", "msg": "not a top-level cost centre"}],
            )
        fy = await self._get_fiscal_year(fiscal_year_id)
        if fy.budget_id != top.id:
            raise NotFoundError(f"fiscal year {fiscal_year_id} not found")
        return top, fy

    async def _budget_steps(self, top_id: UUID) -> list[BudgetPlanStep]:
        """Return the steps of a top-level node in their order."""
        return list(
            (
                await self.session.scalars(
                    select(BudgetPlanStep)
                    .where(BudgetPlanStep.budget_id == top_id)
                    .order_by(BudgetPlanStep.position)
                )
            ).all()
        )

    async def _budget_step_records(self, top_id: UUID) -> list[dict[str, Any]]:
        """Return the steps of a top-level node as the record a version keeps."""
        return plan_rules.step_snapshot(
            [(step.name, step.gremium_id) for step in await self._budget_steps(top_id)]
        )

    async def _steps_out(
        self, records: list[list[dict[str, Any]]]
    ) -> list[tuple[PlanStepOut, ...]]:
        """Turn step records into DTOs with the name of each Gremium.

        One query resolves the names of all lists, so the page never shows an id.
        """
        ids = {
            UUID(step["gremiumId"])
            for steps in records
            for step in steps
            if step.get("gremiumId")
        }
        rows = (
            await self.session.execute(select(Gremium.id, Gremium.name).where(Gremium.id.in_(ids)))
        ).all()
        names = {str(row.id): row.name for row in rows}
        vote_ids = {
            UUID(step["voteId"]) for steps in records for step in steps if step.get("voteId")
        }
        votes = {
            str(row.id): (row.status, row.result)
            for row in (
                await self.session.execute(
                    select(Vote.id, Vote.status, Vote.result).where(Vote.id.in_(vote_ids))
                )
            ).all()
        }
        return [
            tuple(
                PlanStepOut(
                    name=step["name"],
                    gremiumId=step.get("gremiumId"),
                    gremiumName=names.get(step.get("gremiumId") or ""),
                    passedAt=step.get("passedAt"),
                    voteId=step.get("voteId"),
                    voteStatus=votes.get(step.get("voteId") or "", (None, None))[0],
                    voteResult=votes.get(step.get("voteId") or "", (None, None))[1],
                )
                for step in steps
            )
            for steps in records
        ]

    async def _plan_out(self, plan: BudgetPlan, top_id: UUID) -> PlanOut:
        await self.session.flush()
        versions = await self._versions(plan.id)
        lines = [await self._lines(v.id) for v in versions]
        of_budget = await self._budget_step_records(top_id)
        steps = await self._steps_out(
            [of_budget if v.state == "draft" else list(v.steps or []) for v in versions]
        )
        return PlanOut(
            id=plan.id,
            budgetId=top_id,
            fiscalYearId=plan.fiscal_year_id,
            versions=tuple(
                PlanVersionOut(
                    id=v.id,
                    number=v.number,
                    state=cast("PlanState", v.state),
                    createdAt=v.created_at,
                    inForceAt=v.in_force_at,
                    steps=shown,
                    lines=tuple(_line_out(line) for line in rows),
                )
                for v, rows, shown in zip(versions, lines, steps, strict=True)
            ),
        )

    async def _version_context(
        self, version_id: UUID
    ) -> tuple[BudgetPlanVersion, BudgetPlan, FiscalYear, Budget]:
        """Load a version with its plan, fiscal year and top-level node for a write.

        The plan row is locked, so two writes to one plan run one after the other.
        The version is read again after the lock, because a write that waited for the
        lock must see the state that the write before it left.

        Raises:
            NotFoundError: The version does not exist (404).
            ConflictError: `fiscal_year_closed` (409), `plan_not_enabled` (409) when
                the plan switch of the budget is off.
        """
        version = await self.session.get(BudgetPlanVersion, version_id)
        if version is None:
            raise NotFoundError(f"plan version {version_id} not found")
        await self._lock_top_of_plan(version.plan_id)
        plan = (
            await self.session.scalars(
                select(BudgetPlan).where(BudgetPlan.id == version.plan_id).with_for_update()
            )
        ).one_or_none()
        fresh = await self._version_again(version_id)
        if plan is None or fresh is None:
            raise NotFoundError(f"plan version {version_id} not found")
        fy = await self._get_fiscal_year(plan.fiscal_year_id)
        self._refuse_closed(fy)
        top = await self._get_node(fy.budget_id)
        self._require_enabled(top)
        return fresh, plan, fy, top

    async def _version_again(self, version_id: UUID) -> BudgetPlanVersion | None:
        """Read a version again after the locks, `None` when a write before deleted it."""
        return (
            await self.session.scalars(
                select(BudgetPlanVersion)
                .where(BudgetPlanVersion.id == version_id)
                .execution_options(populate_existing=True)
            )
        ).one_or_none()

    async def _lock_top_of_plan(self, plan_id: UUID) -> None:
        """Lock the top-level budget of a plan, when the plan still exists."""
        top_id = await self.session.scalar(
            select(FiscalYear.budget_id)
            .join(BudgetPlan, BudgetPlan.fiscal_year_id == FiscalYear.id)
            .where(BudgetPlan.id == plan_id)
        )
        if top_id is not None:
            await self._lock_tree(top_id)

    @staticmethod
    def _require_enabled(top: Budget) -> None:
        """Refuse a plan write for a budget whose plan switch is off.

        Raises:
            ConflictError: `plan_not_enabled` (409).
        """
        if not top.plan_enabled:
            raise ConflictError(
                "The plan switch of this cost centre is off.", code="plan_not_enabled"
            )

    async def plan_exists(self, fiscal_year_id: UUID) -> bool:
        """Say if the fiscal year has a Haushaltsplan."""
        return await self._plan_of(fiscal_year_id) is not None

    async def _plan_top(self, budget_id: UUID, what: str) -> Budget:
        """Return a top-level node.

        Raises:
            NotFoundError: The node does not exist (404).
            ValidationProblem: `plan_top_level_only` (422) for a node below the top
                level.
        """
        top = await self._get_node(budget_id)
        if top.parent_id is not None:
            raise ValidationProblem(
                f"{what} to a top-level cost centre.",
                code="plan_top_level_only",
                errors=[{"field": "budgetId", "msg": "not a top-level cost centre"}],
            )
        return top

    async def get_plan_steps(self, budget_id: UUID) -> PlanStepsOut:
        """Return the steps of a top-level node."""
        top = await self._plan_top(budget_id, "The plan steps belong")
        (steps,) = await self._steps_out([await self._budget_step_records(top.id)])
        return PlanStepsOut(budgetId=top.id, steps=steps)

    async def set_plan_steps(self, budget_id: UUID, payload: PlanStepsSet) -> PlanStepsOut:
        """Replace the ordered steps of a top-level node.

        A version that left the draft keeps its own steps, so the change reaches only
        a draft and each later version.

        Raises:
            ValidationProblem: `plan_top_level_only` (422), `plan_step_gremium_invalid`
                (422) for a Gremium that does not exist.
            ConflictError: `plan_not_enabled` (409) when the plan switch is off.
        """
        await self._lock_tree(budget_id)
        top = await self._plan_top(budget_id, "The plan steps belong")
        self._require_enabled(top)
        wanted = {step.gremium_id for step in payload.steps if step.gremium_id is not None}
        known = await self.session.scalars(
            select(Gremium.id)
            .where(Gremium.id.in_(wanted))
            .with_for_update(read=True, key_share=True)
        )
        found = set(known.all())
        if wanted - found:
            raise ValidationProblem(
                "A step names a Gremium that does not exist.",
                code="plan_step_gremium_invalid",
                errors=[{"field": "steps", "msg": "gremiumId is not the id of a Gremium"}],
            )
        before = [
            {"name": step.name, "gremiumId": str(step.gremium_id) if step.gremium_id else None}
            for step in await self._budget_steps(top.id)
        ]
        await self.session.execute(delete(BudgetPlanStep).where(BudgetPlanStep.budget_id == top.id))
        self.session.add_all(
            [
                BudgetPlanStep(
                    id=uuid.uuid4(),
                    budget_id=top.id,
                    position=position,
                    name=step.name,
                    gremium_id=step.gremium_id,
                )
                for position, step in enumerate(payload.steps)
            ]
        )
        await self._audit(
            AuditAction.BUDGET_PLAN_STEPS_SET,
            target_type="budget",
            target_id=str(top.id),
            data={
                "pathKey": top.path_key,
                "before": before,
                "after": [
                    {
                        "name": step.name,
                        "gremiumId": str(step.gremium_id) if step.gremium_id else None,
                    }
                    for step in payload.steps
                ],
            },
        )
        await self.session.flush()
        return await self.get_plan_steps(top.id)

    async def set_side(self, budget_id: UUID, side: Side) -> SideOut:
        """Set the side of a direct child of a top-level node and of its subtree.

        Raises:
            ValidationProblem: `side_not_settable` (422) for a top-level node and for
                a node that takes the side of its parent.
            ConflictError: `side_in_plan` (409) when a plan line of the subtree has an
                Ansatz above 0, or when the side becomes income and a line of a
                version that left the draft holds a Vermerk, `fiscal_year_closed`
                (409) when the plan of a closed fiscal year has a line of the subtree.
        """
        await self._lock_tree(budget_id)
        node = await self._get_node(budget_id)
        parent = await self._get_node(node.parent_id) if node.parent_id is not None else None
        if parent is None or parent.parent_id is not None:
            raise ValidationProblem(
                "The side is set on a direct child of a top-level cost centre.",
                code="side_not_settable",
                errors=[{"field": "budgetId", "msg": "not a direct child of the top level"}],
            )
        subtree = await self._subtree(node)
        planned = await self.session.scalar(
            select(func.count())
            .select_from(BudgetPlanLine)
            .where(
                BudgetPlanLine.budget_id.in_([n.id for n in subtree]),
                BudgetPlanLine.amount > 0,
            )
        )
        if planned and node.side != side:
            raise ConflictError(
                "A plan line of this cost centre has an amount. The side cannot change.",
                code="side_in_plan",
            )
        closed = await self.session.scalar(
            select(func.count())
            .select_from(BudgetPlanLine)
            .join(BudgetPlanVersion, BudgetPlanVersion.id == BudgetPlanLine.version_id)
            .join(BudgetPlan, BudgetPlan.id == BudgetPlanVersion.plan_id)
            .join(FiscalYear, FiscalYear.id == BudgetPlan.fiscal_year_id)
            .where(
                BudgetPlanLine.budget_id.in_([n.id for n in subtree]),
                FiscalYear.closed_at.is_not(None),
            )
        )
        if closed and node.side != side:
            raise ConflictError(
                "A closed fiscal year plans this cost centre. The side cannot change.",
                code="fiscal_year_closed",
            )
        ids = [n.id for n in subtree]
        if side == "income" and node.side != side and await self._decided_marks(ids):
            raise ConflictError(
                "A decided plan holds a Vermerk of this cost centre. The side cannot change.",
                code="side_in_plan",
            )
        before = node.side
        for member in subtree:
            member.side = side
        cleared = await self._clear_marks(ids) if side == "income" else []
        await self._audit(
            AuditAction.BUDGET_SIDE_SET,
            target_type="budget",
            target_id=str(node.id),
            data={
                "pathKey": node.path_key,
                "before": before,
                "after": side,
                "clearedMarks": cleared,
            },
        )
        return SideOut(budgetId=node.id, side=side)

    @staticmethod
    def _marked() -> ColumnElement[bool]:
        """The condition of a line that holds a Vermerk or a gesperrt amount."""
        return or_(
            BudgetPlanLine.transferable.is_(True),
            BudgetPlanLine.coverable.is_(True),
            BudgetPlanLine.blocked > 0,
        )

    async def _decided_marks(self, budget_ids: list[UUID]) -> bool:
        """Say if a version that left the draft holds a Vermerk of these cost centers.

        A decided line does not change, and an income line holds no Vermerk, so such
        a cost center keeps its side.
        """
        found = await self.session.scalar(
            select(BudgetPlanLine.id)
            .join(BudgetPlanVersion, BudgetPlanVersion.id == BudgetPlanLine.version_id)
            .where(
                BudgetPlanLine.budget_id.in_(budget_ids),
                BudgetPlanVersion.state != "draft",
                self._marked(),
            )
            .limit(1)
        )
        return found is not None

    async def _clear_marks(self, budget_ids: list[UUID]) -> list[dict[str, object]]:
        """Take the Vermerke off the draft lines of cost centers that become income.

        Only an expense line holds a Vermerk. The lines have an Ansatz of 0, so the
        sums of the draft stay. The return value names each line and what it held,
        for the audit entry.
        """
        lines = (
            await self.session.scalars(
                select(BudgetPlanLine)
                .join(BudgetPlanVersion, BudgetPlanVersion.id == BudgetPlanLine.version_id)
                .where(
                    BudgetPlanLine.budget_id.in_(budget_ids),
                    BudgetPlanVersion.state == "draft",
                    self._marked(),
                )
                .order_by(BudgetPlanLine.version_id, BudgetPlanLine.budget_id)
            )
        ).all()
        nodes = {
            node.id: node
            for node in await self.session.scalars(
                select(Budget).where(Budget.id.in_([line.budget_id for line in lines]))
            )
        }
        cleared: list[dict[str, object]] = [
            {
                "versionId": str(line.version_id),
                "budgetId": str(line.budget_id),
                "pathKey": nodes[line.budget_id].path_key,
                "name": nodes[line.budget_id].name,
                "transferable": line.transferable,
                "coverable": line.coverable,
                "blocked": str(line.blocked),
            }
            for line in lines
        ]
        await self.session.execute(
            update(BudgetPlanLine)
            .where(BudgetPlanLine.id.in_([line.id for line in lines]))
            .values(transferable=False, coverable=False, blocked=Decimal("0.00"))
        )
        return cleared

    async def _stammplan_figures(
        self, top: Budget, nodes: list[Budget], fy: FiscalYear
    ) -> tuple[dict[UUID, Decimal], dict[UUID, tuple[Decimal, Decimal]]]:
        """Return the Ansätze of the Stammplan of `fy` and the allocations it changes.

        The Ansatz of a cost center is its allocation, and a parent holds the sum of
        its children. The plan in force sets the allocations, so the second value
        names each cost center whose allocation then differs, as `(before, after)`.
        """
        rows = (
            await self.session.execute(
                select(BudgetAllocation.budget_id, BudgetAllocation.allocated).where(
                    BudgetAllocation.fiscal_year_id == fy.id
                )
            )
        ).all()
        allocated = {row.budget_id: row.allocated for row in rows}
        amounts = plan_rules.summed_amounts(
            {n.id: n.parent_id for n in nodes},
            {n.id: allocated.get(n.id) or _ZERO for n in nodes if n.id != top.id},
        )
        target = plan_rules.allocations_from_lines(
            [(n.id, n.parent_id, n.side) for n in nodes], amounts, top.id
        )
        return amounts, plan_rules.allocation_changes(allocated, target)

    async def _switch_years(self, top: Budget) -> list[FiscalYear]:
        """Return the open fiscal years of `top` that get a Stammplan from the switch."""
        return [
            fy
            for fy in await self._fiscal_years_of(top.id)
            if fy.closed_at is None and not await self.plan_exists(fy.id)
        ]

    async def preview_plan_switch(
        self, budget_id: UUID, sides: Mapping[UUID, Side] | None = None
    ) -> PlanSwitchPreview:
        """Return the allocations that change when the plan switch goes on.

        `sides` names the side that a form gives a direct child and has not saved yet.
        The preview counts with it, so a person sees the changes before the first
        write. The rows take these sides only in this session: the caller must roll
        the session back and must not commit it.

        Raises:
            ValidationProblem: `plan_top_level_only` (422).
        """
        top = await self._plan_top(budget_id, "The plan switch belongs")
        nodes = await self._subtree(top)
        by_id = {n.id: n for n in nodes}
        parent_of = {n.id: n.parent_id for n in nodes}
        for node in nodes:
            wanted = plan_rules.proposed_side(parent_of, top.id, sides or {}, node.id)
            if wanted is not None:
                node.side = wanted
        figures = [
            (fy, (await self._stammplan_figures(top, nodes, fy))[1])
            for fy in await self._switch_years(top)
        ]
        return PlanSwitchPreview(
            budgetId=top.id,
            changes=tuple(
                PlanSwitchChange(
                    fiscalYearId=fy.id,
                    year=tree_rules.fiscal_year_display(
                        fy.year, top.fiscal_start_month, top.fiscal_start_day
                    ),
                    budgetId=node_id,
                    pathKey=by_id[node_id].path_key,
                    name=by_id[node_id].name,
                    allocated=before.quantize(_CENT),
                    planned=after.quantize(_CENT),
                )
                for fy, changes in figures
                for node_id, (before, after) in sorted(
                    changes.items(), key=lambda item: by_id[item[0]].path_key
                )
            ),
        )

    async def set_plan_switch(
        self, budget_id: UUID, enabled: bool, *, confirm_changes: bool = False
    ) -> PlanSwitchOut:
        """Set the plan switch of a top-level node.

        When the switch goes on, each open fiscal year without a plan gets a Stammplan
        in force from its allocations, and that plan sets the allocations. A closed
        year gets no plan. The switch goes off only while each plan of the budget is a
        Stammplan in force that passed no step, and it deletes those plans, so a plan
        and the allocations never differ.

        Raises:
            ValidationProblem: `plan_top_level_only` (422) for a node below the top
                level, `plan_side_missing` (422) when a node below it has no side.
            ConflictError: `plan_changes_allocations` (409) when the Stammplan changes
                an allocation and the request does not confirm it,
                `plan_switch_has_plans` (409) when the switch goes off and a plan has
                a decision, a draft or a closed fiscal year.
        """
        await self._lock_tree(budget_id)
        top = await self._plan_top(budget_id, "The plan switch belongs")
        if bool(top.plan_enabled) == enabled:
            return PlanSwitchOut(budgetId=top.id, planEnabled=enabled)
        touched = await (
            self._switch_on(top, confirm_changes=confirm_changes)
            if enabled
            else self._switch_off(top)
        )
        top.plan_enabled = enabled
        await self._audit(
            AuditAction.BUDGET_PLAN_SWITCH,
            target_type="budget",
            target_id=str(top.id),
            data={"pathKey": top.path_key, "enabled": enabled, **touched},
        )
        return PlanSwitchOut(budgetId=top.id, planEnabled=enabled)

    async def _switch_on(self, top: Budget, *, confirm_changes: bool) -> dict[str, Any]:
        """Give each open fiscal year without a plan its Stammplan, for the audit data."""
        nodes = await self._subtree(top)
        if any(n.side is None for n in nodes if n.id != top.id):
            raise ValidationProblem(
                "Each cost centre below the top level needs a side first.",
                code="plan_side_missing",
                errors=[{"field": "side", "msg": "a cost centre has no side"}],
            )
        years = await self._switch_years(top)
        figures = [await self._stammplan_figures(top, nodes, fy) for fy in years]
        if any(changes for _amounts, changes in figures) and not confirm_changes:
            raise ConflictError(
                "The Stammplan changes allocations. Confirm the changes.",
                code="plan_changes_allocations",
            )
        created = [
            await self._stammplan_from_allocations(top, fy, nodes, amounts)
            for fy, (amounts, _changes) in zip(years, figures, strict=True)
        ]
        return {
            "createdPlans": [str(plan_id) for plan_id in created],
            "allocations": {
                str(fy.id): _changes_out(changes)
                for fy, (_amounts, changes) in zip(years, figures, strict=True)
                if changes
            },
        }

    async def _switch_off(self, top: Budget) -> dict[str, Any]:
        """Delete the plans of a budget whose switch goes off, for the audit data.

        Raises:
            ConflictError: `plan_switch_has_plans` (409).
        """
        years = await self._fiscal_years_of(top.id)
        plans = [
            (fy, plan)
            for fy, plan in [(fy, await self._plan_of(fy.id)) for fy in years]
            if plan is not None
        ]
        plain = [
            fy.closed_at is None
            and plan_rules.is_plain_stammplan(
                [(v.number, v.state, v.steps or []) for v in await self._versions(plan.id)]
            )
            for fy, plan in plans
        ]
        if not all(plain):
            raise ConflictError(
                "A Haushaltsplan of this cost centre has a decision or a draft.",
                code="plan_switch_has_plans",
            )
        deleted = {
            "deletedPlans": [str(plan.id) for _fy, plan in plans],
            "deletedYears": [fy.year for fy, _plan in plans],
            "deletedVersions": [
                str(version.id) for _fy, plan in plans for version in await self._versions(plan.id)
            ],
        }
        for _fy, plan in plans:
            await self.session.delete(plan)
        await self.session.flush()
        return deleted

    async def _stammplan_from_allocations(
        self, top: Budget, fy: FiscalYear, nodes: list[Budget], amounts: dict[UUID, Decimal]
    ) -> UUID:
        """Create the plan of `fy` with a Stammplan in force and write its allocations."""
        plan = BudgetPlan(id=uuid.uuid4(), fiscal_year_id=fy.id)
        version = BudgetPlanVersion(
            id=uuid.uuid4(),
            plan_id=plan.id,
            number=0,
            state="in_force",
            in_force_at=datetime.now(UTC),
        )
        self.session.add(plan)
        await self.session.flush()
        self.session.add(version)
        await self.session.flush()
        self.session.add_all(
            [
                BudgetPlanLine(
                    id=uuid.uuid4(),
                    version_id=version.id,
                    budget_id=node.id,
                    amount=amounts[node.id],
                    name=node.name,
                    path_key=node.path_key,
                )
                for node in nodes
                if node.id != top.id
            ]
        )
        await self._write_allocations(fy.id, top, nodes, amounts)
        await self._audit_version(plan, version)
        return plan.id

    async def get_plan(self, budget_id: UUID, fiscal_year_id: UUID) -> PlanOut:
        """Return the Haushaltsplan of a fiscal year with every version.

        Raises:
            NotFoundError: `plan_not_found` (404) when the year has no plan.
        """
        top, fy = await self._plan_year(budget_id, fiscal_year_id)
        plan = await self._plan_of(fy.id)
        if plan is None:
            raise NotFoundError("This fiscal year has no Haushaltsplan.", code="plan_not_found")
        return await self._plan_out(plan, top.id)

    async def plan_of_version(self, version_id: UUID) -> PlanOut:
        """Return the Haushaltsplan that holds a version, for a link from its vote.

        Raises:
            NotFoundError: The version does not exist (404). A version that a delete
                takes away after the first read is no error: the answer then holds the
                rows that are left.
        """
        plan = await self.session.scalar(
            select(BudgetPlan)
            .join(BudgetPlanVersion, BudgetPlanVersion.plan_id == BudgetPlan.id)
            .where(BudgetPlanVersion.id == version_id)
        )
        if plan is None:
            raise NotFoundError(f"plan version {version_id} not found")
        fy = await self._get_fiscal_year(plan.fiscal_year_id)
        return await self._plan_out(plan, fy.budget_id)

    async def create_plan(
        self, budget_id: UUID, fiscal_year_id: UUID, payload: PlanCreate
    ) -> PlanOut:
        """Create the Haushaltsplan of a fiscal year with a Stammplan in draft.

        Raises:
            ConflictError: `plan_not_enabled` (409) when the plan switch is off,
                `fiscal_year_closed` (409), `plan_exists` (409) when the year has a
                plan.
            ValidationProblem: `plan_copy_source_invalid` (422) when the source year
                has no version in force or belongs to a different top-level node.
        """
        await self._lock_tree(budget_id)
        top, fy = await self._plan_year(budget_id, fiscal_year_id)
        self._require_enabled(top)
        self._refuse_closed(fy)
        if await self.plan_exists(fy.id):
            raise ConflictError("This fiscal year has a Haushaltsplan.", code="plan_exists")
        source = (
            await self._copy_source(top, payload.copy_from_fiscal_year_id)
            if payload.copy_from_fiscal_year_id is not None
            else []
        )
        plan = BudgetPlan(id=uuid.uuid4(), fiscal_year_id=fy.id)
        self.session.add(plan)
        await self.session.flush()
        version = await self._new_version(plan, 0, source, top)
        await self._audit_version(plan, version, copied_from=payload.copy_from_fiscal_year_id)
        return await self._plan_out(plan, top.id)

    async def _copy_source(
        self, top: Budget, fiscal_year_id: UUID
    ) -> list[BudgetPlanLine]:
        """Return the lines of the version in force of another year of `top`."""
        fy = await self.session.get(FiscalYear, fiscal_year_id)
        plan = await self._plan_of(fiscal_year_id) if fy is not None else None
        in_force = (
            next((v for v in await self._versions(plan.id) if v.state == "in_force"), None)
            if plan is not None
            else None
        )
        if fy is None or fy.budget_id != top.id or in_force is None:
            raise ValidationProblem(
                "The source year has no Haushaltsplan in force.",
                code="plan_copy_source_invalid",
                errors=[{"field": "copyFromFiscalYearId", "msg": "no plan in force"}],
            )
        return await self._lines(in_force.id)

    async def _new_version(
        self, plan: BudgetPlan, number: int, source: list[BudgetPlanLine], top: Budget
    ) -> BudgetPlanVersion:
        """Add a draft version to `plan` with a copy of the `source` lines.

        The copy drops the name and the path key of a decided line, because a draft
        shows the current ones. Each parent of the copy holds the sum of its children,
        because the tree can differ from the tree of the source.
        """
        version = BudgetPlanVersion(
            id=uuid.uuid4(),
            plan_id=plan.id,
            number=number,
            state="draft",
        )
        self.session.add(version)
        await self.session.flush()
        copies = [
            BudgetPlanLine(
                id=uuid.uuid4(),
                version_id=version.id,
                budget_id=line.budget_id,
                amount=line.amount,
                note=line.note,
                transferable=line.transferable,
                coverable=line.coverable,
                blocked=line.blocked,
            )
            for line in source
        ]
        self._resum(copies, {n.id: n.parent_id for n in await self._subtree(top)})
        self.session.add_all(copies)
        return version

    async def _plan_names(self, plan: BudgetPlan) -> dict[str, object]:
        """Return the path key of the budget and the year of a plan, as audit data.

        An entry keeps them, because the ids of a plan that is deleted later resolve
        to no name.
        """
        fy = await self._get_fiscal_year(plan.fiscal_year_id)
        top = await self._get_node(fy.budget_id)
        return {"budget": top.path_key, "year": fy.year}

    async def _audit_version(
        self, plan: BudgetPlan, version: BudgetPlanVersion, *, copied_from: UUID | None = None
    ) -> None:
        await self._audit(
            AuditAction.BUDGET_PLAN_VERSION_CREATE,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
                **await self._plan_names(plan),
                "fiscalYearId": str(plan.fiscal_year_id),
                "versionId": str(version.id),
                "number": version.number,
                "copiedFromFiscalYearId": str(copied_from) if copied_from else None,
            },
        )

    async def create_nachtrag(self, budget_id: UUID, fiscal_year_id: UUID) -> PlanOut:
        """Add a Nachtrag in draft with a copy of the lines of the version in force.

        Raises:
            NotFoundError: `plan_not_found` (404).
            ConflictError: `fiscal_year_closed` (409), `plan_draft_exists` (409) when
                a version before `in_force` exists, `plan_not_in_force` (409) when no
                version is in force.
        """
        await self._lock_tree(budget_id)
        top, fy = await self._plan_year(budget_id, fiscal_year_id)
        self._require_enabled(top)
        self._refuse_closed(fy)
        plan = await self._plan_of(fy.id)
        if plan is None:
            raise NotFoundError("This fiscal year has no Haushaltsplan.", code="plan_not_found")
        versions = await self._versions(plan.id)
        if any(v.state in plan_rules.OPEN_STATES for v in versions):
            raise ConflictError(
                "The plan has a version that is not in force yet.", code="plan_draft_exists"
            )
        in_force = next((v for v in versions if v.state == "in_force"), None)
        if in_force is None:
            raise ConflictError("The plan has no version in force.", code="plan_not_in_force")
        version = await self._new_version(
            plan, max(v.number for v in versions) + 1, await self._lines(in_force.id), top
        )
        await self._audit_version(plan, version)
        return await self._plan_out(plan, top.id)

    async def set_line(self, version_id: UUID, budget_id: UUID, payload: PlanLineSet) -> PlanOut:
        """Set the line of one cost center in a draft version.

        A cost center with a child in the version holds the sum of the Ansätze of
        those children: the amount of the payload does not count for it, and each
        ancestor up to the node below the top level follows a change of a child. A
        blocked amount of an ancestor falls with its Ansatz.

        Raises:
            NotFoundError: The version or the cost center does not exist (404).
            ConflictError: `fiscal_year_closed` (409), `plan_version_locked` (409) for
                a version that is not a draft.
            ValidationProblem: `plan_line_node_invalid` (422) for the top-level node
                or a node of a different tree, `plan_side_missing` (422),
                `plan_marks_income` (422), `plan_blocked_above_amount` (422),
                `plan_amount_too_large` (422) when the sum of a parent or of a side
                passes the largest amount.
        """
        version, plan, _fy, top = await self._version_context(version_id)
        if version.state != "draft":
            raise ConflictError(
                "Only a draft version can be edited.", code="plan_version_locked"
            )
        nodes = await self._subtree(top)
        node = next((n for n in nodes if n.id == budget_id and n.id != top.id), None)
        if node is None:
            await self._get_node(budget_id)
            raise ValidationProblem(
                "The cost centre is not below the top-level cost centre of this plan.",
                code="plan_line_node_invalid",
                errors=[{"field": "budgetId", "msg": "not below the top level of the plan"}],
            )
        lines = {line.budget_id: line for line in await self._lines(version.id)}
        previous = lines.get(node.id)
        before = str(previous.amount) if previous is not None else None
        parent_of = {n.id: n.parent_id for n in nodes}
        giver = (
            lines.get(plan_rules.first_child_of(node.id, parent_of, list(lines)) or top.id)
            if payload.amount == 0
            else None
        )
        wanted = self._wanted(payload, previous, giver)
        amount = plan_rules.summed_amounts(
            parent_of,
            {**{bid: line.amount for bid, line in lines.items()}, node.id: wanted.amount},
        )[node.id]
        self._check_line(node, wanted, amount)
        own = self._line_for(version.id, node.id, lines)
        own.amount = amount
        own.note = wanted.note
        own.transferable = wanted.transferable
        own.coverable = wanted.coverable
        own.blocked = wanted.blocked
        above = [
            self._line_for(version.id, ancestor, lines)
            for ancestor in plan_rules.ancestors_below(node.id, parent_of, top.id)
        ]
        if giver is not None:
            giver.blocked = _ZERO
        kept = {id(ln): ln for ln in (*lines.values(), own, *above)}
        raised = self._resum(list(kept.values()), parent_of)
        self._refuse_large_side(top, nodes, {ln.budget_id: ln.amount for ln in kept.values()})
        await self._audit(
            AuditAction.BUDGET_PLAN_LINE_SET,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
                "versionId": str(version.id),
                "number": version.number,
                "budgetId": str(node.id),
                "pathKey": node.path_key,
                "name": node.name,
                "amount": str(amount),
                "previousAmount": before,
                "note": wanted.note,
                "transferable": wanted.transferable,
                "coverable": wanted.coverable,
                "blocked": str(wanted.blocked),
                "raised": {str(k): str(v) for k, v in raised.items()},
            },
        )
        return await self._plan_out(plan, top.id)

    @staticmethod
    def _wanted(
        payload: PlanLineSet, previous: BudgetPlanLine | None, giver: BudgetPlanLine | None
    ) -> PlanLineSet:
        """Return the whole line that a request asks for.

        A field that the request leaves out keeps the value of the line. The first
        child line of a parent takes the Ansatz and the blocked amount of the parent
        (`giver`), because the parent then holds the sum of its children and its own
        Ansatz would be lost. The caller passes no `giver` for a request that names an
        Ansatz above 0.
        """
        named = payload.model_fields_set
        kept = (
            {
                "amount": previous.amount,
                "note": previous.note,
                "transferable": bool(previous.transferable),
                "coverable": bool(previous.coverable),
                "blocked": previous.blocked if previous.blocked is not None else _ZERO,
            }
            if previous is not None
            else {}
        )
        given = (
            {
                "amount": giver.amount,
                "blocked": giver.blocked if giver.blocked is not None else _ZERO,
            }
            if giver is not None
            else {}
        )
        return PlanLineSet.model_validate(
            {**kept, **{name: getattr(payload, name) for name in named}, **given}
        )

    def _line_for(
        self, version_id: UUID, budget_id: UUID, lines: dict[UUID, BudgetPlanLine]
    ) -> BudgetPlanLine:
        """Return the line of a cost center, a new one in the session when it is missing."""
        existing = lines.get(budget_id)
        if existing is not None:
            return existing
        line = BudgetPlanLine(
            id=uuid.uuid4(),
            version_id=version_id,
            budget_id=budget_id,
            amount=_ZERO,
            blocked=_ZERO,
        )
        self.session.add(line)
        return line

    @staticmethod
    def _check_line(node: Budget, payload: PlanLineSet, amount: Decimal) -> None:
        """Check a line against the side of its cost center and its Ansatz `amount`.

        Raises:
            ValidationProblem: `plan_side_missing`, `plan_marks_income` or
                `plan_blocked_above_amount` (422).
        """
        if node.side is None:
            raise ValidationProblem(
                "The cost centre has no side.",
                code="plan_side_missing",
                errors=[{"field": "side", "msg": "the cost centre has no side"}],
            )
        marked = payload.transferable or payload.coverable or payload.blocked > 0
        if node.side == "income" and marked:
            raise ValidationProblem(
                "A line of an income cost centre has no Vermerk.",
                code="plan_marks_income",
                errors=[{"field": "transferable", "msg": "no Vermerk on an income line"}],
            )
        if payload.blocked > amount:
            raise ValidationProblem(
                "The blocked amount is above the Ansatz.",
                code="plan_blocked_above_amount",
                errors=[{"field": "blocked", "msg": "above the Ansatz"}],
            )

    async def delete_line(self, version_id: UUID, budget_id: UUID) -> PlanOut:
        """Remove the line of one cost center from a draft version.

        The cost center then does not belong to the plan of that year. Each ancestor
        that still has a child in the version falls to the sum of those children.

        Raises:
            NotFoundError: The version does not exist, or `plan_line_not_found` (404).
            ConflictError: `fiscal_year_closed` (409), `plan_version_locked` (409).
            ValidationProblem: `plan_line_has_children` (422) while a child cost
                center has a line.
        """
        version, plan, _fy, top = await self._version_context(version_id)
        if version.state != "draft":
            raise ConflictError(
                "Only a draft version can be edited.", code="plan_version_locked"
            )
        lines = {line.budget_id: line for line in await self._lines(version.id)}
        line = lines.get(budget_id)
        if line is None:
            raise NotFoundError(
                "The version has no line for this cost centre.", code="plan_line_not_found"
            )
        nodes = await self._subtree(top)
        if any(n.parent_id == budget_id and n.id in lines for n in nodes):
            raise ValidationProblem(
                "A child cost centre has a line. Remove it first.",
                code="plan_line_has_children",
                errors=[{"field": "budgetId", "msg": "a child cost centre has a line"}],
            )
        raised = self._resum(
            [ln for ln in lines.values() if ln is not line], {n.id: n.parent_id for n in nodes}
        )
        await self.session.delete(line)
        await self._audit(
            AuditAction.BUDGET_PLAN_LINE_SET,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
                "versionId": str(version.id),
                "number": version.number,
                "budgetId": str(budget_id),
                **{
                    key: value
                    for n in nodes
                    if n.id == budget_id
                    for key, value in (("pathKey", n.path_key), ("name", n.name))
                },
                "amount": None,
                "previousAmount": str(line.amount),
                "raised": {str(k): str(v) for k, v in raised.items()},
            },
        )
        return await self._plan_out(plan, top.id)

    @staticmethod
    def _require_lines(lines: list[BudgetPlanLine]) -> None:
        """Refuse a version without a line, because it would set each allocation to 0.

        Raises:
            ValidationProblem: `plan_empty` (422).
        """
        if not lines:
            raise ValidationProblem(
                "The version has no line.",
                code="plan_empty",
                errors=[{"field": "state", "msg": "the version has no line"}],
            )

    def _require_balanced(
        self, top: Budget, nodes: list[Budget], amounts: dict[UUID, Decimal]
    ) -> None:
        """Refuse a version whose income Ansätze differ from its expense Ansätze.

        Raises:
            ValidationProblem: `plan_not_balanced` (422), `plan_amount_too_large` (422)
                when the sum of a side passes the largest amount.
        """
        direct = [(n.side, amounts.get(n.id, _ZERO)) for n in nodes if n.parent_id == top.id]
        income, expense = plan_rules.side_sums(direct)
        if not plan_rules.is_balanced(direct):
            raise ValidationProblem(
                "The plan is not balanced.",
                code="plan_not_balanced",
                errors=[
                    {"field": "state", "msg": f"income {income} differs from expenses {expense}"}
                ],
            )
        self._refuse_large_side(top, nodes, amounts)

    @staticmethod
    def _refuse_large_side(
        top: Budget, nodes: Sequence[Budget], amounts: Mapping[UUID, Decimal]
    ) -> None:
        """Refuse a plan whose income or expense sum passes the largest amount.

        The top-level cost center gets the expense sum as its allocation when the plan
        comes into force, and the database holds no larger amount.

        Raises:
            ValidationProblem: `plan_amount_too_large` (422).
        """
        direct = [(n.side, amounts.get(n.id, _ZERO)) for n in nodes if n.parent_id == top.id]
        if max(plan_rules.side_sums(direct)) > plan_rules.MAX_AMOUNT:
            raise ValidationProblem(
                "The sum of a side is above the largest amount.",
                code="plan_amount_too_large",
                errors=[{"field": "amount", "msg": "the sum of a side is too large"}],
            )

    @staticmethod
    def _keep_names(lines: list[BudgetPlanLine], nodes: list[Budget]) -> None:
        """Write the current name and path key of each cost center into its line."""
        names = {n.id: (n.name, n.path_key) for n in nodes}
        for line in lines:
            line.name = names[line.budget_id][0]
            line.path_key = names[line.budget_id][1]

    async def _open_step(
        self, version: BudgetPlanVersion, top: Budget
    ) -> tuple[list[dict[str, Any]], int]:
        """Return the steps of a version and the index of its next step.

        A draft takes the steps of its budget and leaves the draft with this call:
        the version must have a line and be balanced, and each line keeps the name
        and the path key of its cost center.

        Raises:
            ConflictError: `plan_state_invalid` (409) for a version in force or
                replaced, `plan_no_step_left` (409) when the version has no step that
                is not passed.
            ValidationProblem: `plan_empty` or `plan_not_balanced` (422) for a draft.
        """
        if version.state not in plan_rules.OPEN_STATES:
            raise ConflictError(
                f"A version in {version.state!r} passes no step.", code="plan_state_invalid"
            )
        first = version.state == "draft"
        steps = await self._budget_step_records(top.id) if first else list(version.steps or [])
        index = plan_rules.next_step(steps)
        if index is None:
            raise ConflictError("The version has no step left.", code="plan_no_step_left")
        if first:
            nodes = await self._subtree(top)
            lines = await self._lines(version.id)
            self._require_lines(lines)
            self._require_balanced(top, nodes, {line.budget_id: line.amount for line in lines})
            self._keep_names(lines, nodes)
        return steps, index

    async def pass_next_step(
        self, version_id: UUID, *, by_vote: UUID | None = None, expected: int | None = None
    ) -> PlanOut:
        """Record the next step of a version as passed.

        The first step takes the version out of the draft (`_open_step`).

        Raises:
            NotFoundError: The version does not exist (404).
            ConflictError: `fiscal_year_closed` (409), `plan_state_invalid` (409),
                `plan_no_step_left` (409), `plan_step_has_vote` (409) for a record by
                hand while the step has a vote that is not cancelled,
                `plan_step_not_next` (409) when `expected` names a step that is not
                the next one, so two requests for one step pass one step.
            ValidationProblem: `plan_not_balanced` (422) at the first step.
        """
        version, plan, fy, top = await self._version_context(version_id)
        steps, index = await self._open_step(version, top)
        if expected is not None and expected != index:
            raise ConflictError(
                "The step that the request names is not the next step.",
                code="plan_step_not_next",
            )
        if by_vote is None and await self._vote_status(steps[index].get("voteId")) in (
            "draft",
            "open",
            "closed",
        ):
            raise ConflictError(
                "The step has a vote. Only its result passes the step.",
                code="plan_step_has_vote",
            )
        version.state = "in_progress"
        version.steps = plan_rules.with_step_passed(steps, index, datetime.now(UTC).isoformat())
        await self._audit(
            AuditAction.BUDGET_PLAN_STEP,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
                "budget": top.path_key,
                "year": fy.year,
                "fiscalYearId": str(fy.id),
                "versionId": str(version.id),
                "number": version.number,
                "step": steps[index]["name"],
                "gremiumId": steps[index]["gremiumId"],
                "voteId": str(by_vote) if by_vote else None,
            },
        )
        return await self._plan_out(plan, top.id)

    async def _vote_status(self, vote_id: str | None) -> str | None:
        """Return the status of the vote of a step, or `None` when the vote is gone."""
        return (
            await self.session.scalar(select(Vote.status).where(Vote.id == UUID(vote_id)))
            if vote_id
            else None
        )

    async def _vote_runs(self, vote_id: str | None) -> bool:
        """Say if the vote of a step is a draft or open, so the step waits for it."""
        return await self._vote_status(vote_id) in ("draft", "open")

    async def create_step_vote(self, version_id: UUID) -> PlanOut:
        """Create the vote of the Gremium of the next step, as a draft.

        The vote is a vote of that Gremium without a meeting and without an
        application, with the quorum of the Gremium. The step keeps its id. A draft
        version leaves the draft with this call (`_open_step`), because the Gremium
        must decide on a plan that does not change. A step whose vote ended without
        an accepted result, or whose vote is gone, takes a new vote.

        The voting service commits the vote, so this call commits the version too.

        Raises:
            NotFoundError: The version does not exist (404).
            ConflictError: `fiscal_year_closed` (409), `plan_state_invalid` (409),
                `plan_no_step_left` (409), `plan_step_vote_runs` (409) when the vote
                of the step is a draft or open.
            ValidationProblem: `plan_not_balanced` (422) for a draft,
                `plan_step_no_gremium` (422) for a step without a Gremium.
        """
        version, plan, fy, top = await self._version_context(version_id)
        steps, index = await self._open_step(version, top)
        step = steps[index]
        if not step["gremiumId"]:
            raise ValidationProblem(
                "The step names no Gremium.",
                code="plan_step_no_gremium",
                errors=[{"field": "step", "msg": "no gremium"}],
            )
        if await self._vote_runs(step.get("voteId")):
            raise ConflictError("The step already has a vote.", code="plan_step_vote_runs")
        gremium_id = UUID(step["gremiumId"])
        if await self.session.get(Gremium, gremium_id) is None:
            raise ValidationProblem(
                "The Gremium of the step does not exist.",
                code="plan_step_no_gremium",
                errors=[{"field": "step", "msg": "the gremium is gone"}],
            )
        vote_id = uuid.uuid4()
        version.state = "in_progress"
        version.steps = plan_rules.with_step_vote(steps, index, str(vote_id))
        await self._audit(
            AuditAction.BUDGET_PLAN_STEP_VOTE,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
                "budget": top.path_key,
                "year": fy.year,
                "fiscalYearId": str(fy.id),
                "versionId": str(version.id),
                "number": version.number,
                "step": step["name"],
                "gremiumId": step["gremiumId"],
                "voteId": str(vote_id),
            },
        )
        await self.session.flush()
        quorum = await self.session.scalar(
            select(Gremium.quorum_percent).where(Gremium.id == gremium_id)
        )
        await VotingService(self.session).create_internal(
            None,
            VoteCreateInternal(
                config=VoteConfig.model_validate(plan_rules.step_vote_config(quorum)),
                eligibleGroup=gremium_id,
                question=plan_rules.step_vote_question(
                    top.name,
                    tree_rules.fiscal_year_display(
                        fy.year, top.fiscal_start_month, top.fiscal_start_day
                    ),
                    plan_rules.version_name(version.number),
                    step["name"],
                ),
                eligibleCount=await MeetingRules(self.session).vote_eligible_count(gremium_id),
                planVersionId=version.id,
            ),
            vote_id=vote_id,
            actor=self.actor,
        )
        return await self._plan_out(plan, top.id)

    async def lock_plan_of_version(self, version_id: UUID) -> BudgetPlanVersion | None:
        """Lock the plan row of a version and return the version as the lock sees it.

        The close of a step vote holds the vote row and calls this, so it reads the
        state that a plan write before it left: a version that went back to draft in
        between passes no step.
        """
        version = await self.session.get(BudgetPlanVersion, version_id)
        if version is None:
            return None
        await self._lock_top_of_plan(version.plan_id)
        await self.session.scalars(
            select(BudgetPlan.id).where(BudgetPlan.id == version.plan_id).with_for_update()
        )
        return await self._version_again(version_id)

    async def pass_step_by_vote(self, version_id: UUID, vote_id: UUID) -> bool:
        """Pass the next step of a version for its accepted vote, and say if it did.

        The close of the vote calls this in its own transaction. The call passes
        nothing when the vote is not the vote of the next step (the version went back
        to draft, or the step was passed by hand) or when the fiscal year is closed,
        because the close of a vote must not fail for the state of the plan.
        """
        version = await self.lock_plan_of_version(version_id)
        if (
            version is None
            or version.state != "in_progress"
            or not plan_rules.vote_decides_next(list(version.steps or []), str(vote_id))
        ):
            return False
        try:
            await self.pass_next_step(version_id, by_vote=vote_id)
        except ConflictError:
            return False
        return True

    async def set_plan_state(self, version_id: UUID, payload: PlanStateSet) -> PlanOut:
        """Bring a version into force, or move a version in progress back to draft.

        A version comes into force after its last step, or from the draft when its
        budget has no steps. It then replaces the earlier version in force and writes
        the allocations. A version that moves back to draft loses its passed steps, and the
        votes of its steps end: a draft vote is deleted and an open vote is cancelled.

        Raises:
            NotFoundError: The version does not exist (404).
            ConflictError: `fiscal_year_closed` (409), `plan_state_invalid` (409).
            ValidationProblem: `plan_not_balanced` (422) for a draft that comes into
                force, `plan_empty` (422) for a version without a line.
        """
        if payload.state == "draft":
            await VotingService(self.session).lock_for_plan_version(version_id)
        version, plan, fy, top = await self._version_context(version_id)
        current = version.state
        target = payload.state
        changed = await self._move(version, plan, fy, top, target)
        version.state = target
        await self._audit(
            AuditAction.BUDGET_PLAN_STATE,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
                "budget": top.path_key,
                "year": fy.year,
                "fiscalYearId": str(fy.id),
                "versionId": str(version.id),
                "number": version.number,
                "before": current,
                "after": target,
                "allocations": _changes_out(changed),
            },
        )
        return await self._plan_out(plan, top.id)

    async def _move(
        self,
        version: BudgetPlanVersion,
        plan: BudgetPlan,
        fy: FiscalYear,
        top: Budget,
        target: PlanTarget,
    ) -> dict[UUID, tuple[Decimal, Decimal]]:
        """Run the state change to `target` and return the allocations it changed."""
        lines = await self._lines(version.id)
        match target:
            case "in_force":
                return await self._enter_force(version, plan, fy, top, lines)
            case "draft":
                return await self._back_to_draft(version, lines)
            case _:  # pragma: no cover
                assert_never(target)

    async def _enter_force(
        self,
        version: BudgetPlanVersion,
        plan: BudgetPlan,
        fy: FiscalYear,
        top: Budget,
        lines: list[BudgetPlanLine],
    ) -> dict[UUID, tuple[Decimal, Decimal]]:
        """Bring a version into force and return the allocations it changed.

        Raises:
            ConflictError: `plan_state_invalid` (409).
            ValidationProblem: `plan_not_balanced` or `plan_empty` (422).
        """
        current = version.state
        if current not in plan_rules.OPEN_STATES:
            raise ConflictError(
                f"A version in {current!r} cannot come into force.", code="plan_state_invalid"
            )
        steps = (
            await self._budget_step_records(top.id)
            if current == "draft"
            else list(version.steps or [])
        )
        if not plan_rules.can_enter_force(current, steps):
            raise ConflictError(
                "The version has a step that is not passed.", code="plan_state_invalid"
            )
        self._require_lines(lines)
        nodes = await self._subtree(top)
        amounts = {line.budget_id: line.amount for line in lines}
        if current == "draft":
            self._require_balanced(top, nodes, amounts)
            self._keep_names(lines, nodes)
        await self._replace_in_force(plan.id)
        version.in_force_at = datetime.now(UTC)
        return await self._write_allocations(fy.id, top, nodes, amounts)

    async def _back_to_draft(
        self, version: BudgetPlanVersion, lines: list[BudgetPlanLine]
    ) -> dict[UUID, tuple[Decimal, Decimal]]:
        """Move a version in progress back to draft. It changes no allocation.

        Raises:
            ConflictError: `plan_state_invalid` (409).
        """
        if not plan_rules.can_return_to_draft(version.state):
            raise ConflictError(
                f"A version in {version.state!r} cannot move back to draft.",
                code="plan_state_invalid",
            )
        await VotingService(self.session).end_for_plan_version(version.id, actor=self.actor)
        version.steps = []
        for line in lines:
            line.name = None
            line.path_key = None
        return {}

    async def delete_version(self, version_id: UUID) -> None:
        """Delete a draft version, and the plan with it when it has no other version.

        Raises:
            NotFoundError: The version does not exist (404).
            ConflictError: `fiscal_year_closed` (409), `plan_not_enabled` (409),
                `plan_version_locked` (409) for a version that is not a draft.
        """
        version, plan, fy, top = await self._version_context(version_id)
        if version.state != "draft":
            raise ConflictError(
                "Only a draft version can be deleted.", code="plan_version_locked"
            )
        alone = len(await self._versions(plan.id)) == 1
        await self._audit(
            AuditAction.BUDGET_PLAN_VERSION_DELETE,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
                "budget": top.path_key,
                "year": fy.year,
                "fiscalYearId": str(fy.id),
                "versionId": str(version.id),
                "number": version.number,
                "planDeleted": alone,
            },
        )
        await self.session.delete(plan if alone else version)
        await self.session.flush()

    async def create_plan_node(self, version_id: UUID, payload: PlanNodeCreate) -> PlanOut:
        """Create a cost center and its line in a draft version, in one transaction.

        Raises:
            NotFoundError: The version or the parent does not exist (404).
            ConflictError: `fiscal_year_closed` (409), `plan_version_locked` (409),
                `budget_key_exists` (409).
            ValidationProblem: `plan_line_node_invalid` (422) for a parent outside
                the tree of the plan, `plan_side_missing` (422) for a direct child of
                the budget without a side.
        """
        version, _plan, _fy, top = await self._version_context(version_id)
        if version.state != "draft":
            raise ConflictError(
                "A cost centre is created only in a draft version.",
                code="plan_version_locked",
            )
        parent = next((n for n in await self._subtree(top) if n.id == payload.parent_id), None)
        if parent is None:
            await self._get_node(payload.parent_id)
            raise ValidationProblem(
                "The parent is not in the tree of this plan.",
                code="plan_line_node_invalid",
                errors=[{"field": "parentId", "msg": "not in the tree of the plan"}],
            )
        if payload.side is not None and parent.id != top.id:
            raise ValidationProblem(
                "The side is set on a direct child of a top-level cost centre.",
                code="side_not_settable",
                errors=[{"field": "side", "msg": "not a direct child of the top level"}],
            )
        side = payload.side if parent.id == top.id else parent.side
        if side is None:
            raise ValidationProblem(
                "A cost centre directly below the budget needs a side.",
                code="plan_side_missing",
                errors=[{"field": "side", "msg": "the cost centre has no side"}],
            )
        if await self._sibling_exists(parent.id, payload.key):
            raise ConflictError(
                f"budget key {payload.key!r} already exists under this parent",
                code="budget_key_exists",
            )
        node = Budget(
            id=uuid.uuid4(),
            parent_id=parent.id,
            gremium_id=parent.gremium_id,
            key=payload.key,
            path_key=tree_rules.compose_path_key(parent.path_key, payload.key),
            name=payload.name,
            side=side,
        )
        self.session.add(node)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise NodeOps._flush_error(exc, payload.key) from exc
        await self._audit(
            AuditAction.BUDGET_NODE_CREATE,
            target_type="budget",
            target_id=str(node.id),
            data={
                "pathKey": node.path_key,
                "gremiumId": str(parent.gremium_id) if parent.gremium_id else None,
                "decisionGremiumId": None,
            },
        )
        await self.session.flush()
        return await self.set_line(version.id, node.id, PlanLineSet(amount=payload.amount))

    async def _replace_in_force(self, plan_id: UUID) -> None:
        """Set the version in force of a plan to replaced, before a new one takes over.

        The flush keeps the unique index on the version in force satisfied.
        """
        for earlier in await self._versions(plan_id):
            if earlier.state == "in_force":
                earlier.state = "replaced"
        await self.session.flush()

    async def _write_allocations(
        self,
        fiscal_year_id: UUID,
        top: Budget,
        nodes: list[Budget],
        amounts: dict[UUID, Decimal],
    ) -> dict[UUID, tuple[Decimal, Decimal]]:
        """Write the allocation of each cost center from the plan that comes into force.

        Returns:
            `(before, after)` for each cost center whose allocation changed.
        """
        target = plan_rules.allocations_from_lines(
            [(n.id, n.parent_id, n.side) for n in nodes], amounts, top.id
        )
        existing = {
            alloc.budget_id: alloc
            for alloc in (
                await self.session.scalars(
                    select(BudgetAllocation).where(
                        BudgetAllocation.fiscal_year_id == fiscal_year_id,
                        BudgetAllocation.budget_id.in_([n.id for n in nodes]),
                    )
                )
            ).all()
        }
        changes = plan_rules.allocation_changes(
            {node: row.allocated for node, row in existing.items()}, target
        )
        self.session.add_all(
            [
                BudgetAllocation(
                    id=uuid.uuid4(),
                    budget_id=node.id,
                    fiscal_year_id=fiscal_year_id,
                    allocated=target[node.id],
                )
                for node in nodes
                if node.id not in existing
            ]
        )
        for node_id, row in existing.items():
            row.allocated = target[node_id]
        return changes
