"""Haushaltsplan: side, plan switch, versions, lines and state changes.

The decisions live in `app.modules.budget.plan_rules`. The methods here read the
rows, ask the rules and write the result. They do not commit: the router commits
after the method returns, so a refused request leaves no row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, assert_never, cast
from uuid import UUID

from sqlalchemy import delete, func, select

from app.modules.audit.actions import AuditAction
from app.modules.budget import plan_rules, tree_rules
from app.modules.budget.plan_models import (
    BudgetPlan,
    BudgetPlanLine,
    BudgetPlanStep,
    BudgetPlanVersion,
)
from app.modules.budget.plan_rules import PlanState, Side
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
    PlanSwitchOut,
    PlanVersionOut,
    SideOut,
)
from app.modules.budget.tree.allocations import AllocationOps
from app.modules.budget.tree.nodes import NodeOps
from app.modules.budget.tree.service_base import _ZERO, _subtree_ids
from app.modules.budget.tree_models import Budget, BudgetAllocation, FiscalYear
from app.modules.gremien.models import Gremium
from app.modules.meetings.rules import MeetingRules
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteCreateInternal
from app.modules.voting.service import VotingService
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem


def _assign(row: object, **values: object) -> None:
    """Write column values into an ORM row."""
    for name, value in values.items():
        setattr(row, name, value)


def _line_out(line: BudgetPlanLine) -> PlanLineOut:
    return PlanLineOut(
        budgetId=line.budget_id,
        amount=line.amount,
        note=line.note,
        name=line.name,
        pathKey=line.path_key,
        transferable=bool(line.transferable),
        coverable=bool(line.coverable),
        blocked=line.blocked if line.blocked is not None else _ZERO,
    )


class PlanOps(NodeOps, AllocationOps):
    """Read and write the Haushaltsplan of a fiscal year."""

    async def _subtree(self, top: Budget) -> list[Budget]:
        """Return `top` and every node below it."""
        return list(
            (await self.session.scalars(select(Budget).where(Budget.id.in_(_subtree_ids(top)))))
            .all()
        )

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

    async def _lines(self, version_id: UUID) -> list[BudgetPlanLine]:
        return list(
            (
                await self.session.scalars(
                    select(BudgetPlanLine).where(BudgetPlanLine.version_id == version_id)
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

        Raises:
            NotFoundError: The version does not exist (404).
            ConflictError: `fiscal_year_closed` (409).
        """
        version = await self.session.get(BudgetPlanVersion, version_id)
        if version is None:
            raise NotFoundError(f"plan version {version_id} not found")
        plan = (
            await self.session.scalars(
                select(BudgetPlan).where(BudgetPlan.id == version.plan_id).with_for_update()
            )
        ).one()
        fy = await self._get_fiscal_year(plan.fiscal_year_id)
        self._refuse_closed(fy)
        top = await self._get_node(fy.budget_id)
        return version, plan, fy, top

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
        """
        top = await self._plan_top(budget_id, "The plan steps belong")
        wanted = {step.gremium_id for step in payload.steps if step.gremium_id is not None}
        known = await self.session.scalars(select(Gremium.id).where(Gremium.id.in_(wanted)))
        found = set(known.all())
        if wanted - found:
            raise ValidationProblem(
                "A step names a Gremium that does not exist.",
                code="plan_step_gremium_invalid",
                errors=[{"field": "steps", "msg": "gremiumId is not the id of a Gremium"}],
            )
        before = [step.name for step in await self._budget_steps(top.id)]
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
                "after": [step.name for step in payload.steps],
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
                Ansatz above 0.
        """
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
        before = node.side
        for member in subtree:
            member.side = side
        await self._audit(
            AuditAction.BUDGET_SIDE_SET,
            target_type="budget",
            target_id=str(node.id),
            data={"pathKey": node.path_key, "before": before, "after": side},
        )
        return SideOut(budgetId=node.id, side=side)

    async def set_plan_switch(self, budget_id: UUID, enabled: bool) -> PlanSwitchOut:
        """Set the plan switch of a top-level node.

        When the switch goes on, each open fiscal year without a plan gets a Stammplan
        in force whose Ansätze equal the allocations. A closed year gets no plan. When
        the switch goes off, the plans stay, and the plan rules no longer apply.

        Raises:
            ValidationProblem: `plan_top_level_only` (422) for a node below the top
                level, `plan_side_missing` (422) when a node below it has no side.
        """
        top = await self._plan_top(budget_id, "The plan switch belongs")
        below = [n for n in await self._subtree(top) if n.id != top.id]
        if enabled and any(n.side is None for n in below):
            raise ValidationProblem(
                "Each cost centre below the top level needs a side first.",
                code="plan_side_missing",
                errors=[{"field": "side", "msg": "a cost centre has no side"}],
            )
        changed = bool(top.plan_enabled) != enabled
        _assign(top, plan_enabled=enabled)
        created = (
            [
                await self._stammplan_from_allocations(fy, below)
                for fy in await self._fiscal_years_of(top.id)
                if fy.closed_at is None and not await self.plan_exists(fy.id)
            ]
            if enabled
            else []
        )
        if changed or created:
            await self._audit(
                AuditAction.BUDGET_PLAN_SWITCH,
                target_type="budget",
                target_id=str(top.id),
                data={
                    "pathKey": top.path_key,
                    "enabled": enabled,
                    "createdPlans": [str(plan_id) for plan_id in created],
                },
            )
        return PlanSwitchOut(budgetId=top.id, planEnabled=enabled)

    async def _stammplan_from_allocations(self, fy: FiscalYear, below: list[Budget]) -> UUID:
        """Create the plan of `fy` with a Stammplan in force from the allocations."""
        rows = (
            await self.session.execute(
                select(BudgetAllocation.budget_id, BudgetAllocation.allocated).where(
                    BudgetAllocation.fiscal_year_id == fy.id
                )
            )
        ).all()
        allocated = {row.budget_id: row.allocated for row in rows}
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
                    amount=allocated.get(node.id) or _ZERO,
                    name=node.name,
                    path_key=node.path_key,
                )
                for node in below
            ]
        )
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
        top, fy = await self._plan_year(budget_id, fiscal_year_id)
        if not top.plan_enabled:
            raise ConflictError(
                "The plan switch of this cost centre is off.", code="plan_not_enabled"
            )
        self._refuse_closed(fy)
        await self._lock_budget(top.id)
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
        version = await self._new_version(plan, 0, source)
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
        self, plan: BudgetPlan, number: int, source: list[BudgetPlanLine]
    ) -> BudgetPlanVersion:
        """Add a draft version to `plan` with a copy of the `source` lines.

        The copy drops the name and the path key of a decided line, because a draft
        shows the current ones.
        """
        version = BudgetPlanVersion(
            id=uuid.uuid4(),
            plan_id=plan.id,
            number=number,
            state="draft",
        )
        self.session.add(version)
        await self.session.flush()
        self.session.add_all(
            [
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
        )
        return version

    async def _audit_version(
        self, plan: BudgetPlan, version: BudgetPlanVersion, *, copied_from: UUID | None = None
    ) -> None:
        await self._audit(
            AuditAction.BUDGET_PLAN_VERSION_CREATE,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
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
        top, fy = await self._plan_year(budget_id, fiscal_year_id)
        self._refuse_closed(fy)
        await self._lock_budget(top.id)
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
            plan, max(v.number for v in versions) + 1, await self._lines(in_force.id)
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
                `plan_marks_income` (422), `plan_blocked_above_amount` (422).
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
        parent_of = {n.id: n.parent_id for n in nodes}
        has_children = any(n.parent_id == node.id and n.id in lines for n in nodes)
        amount = (
            plan_rules.children_sum(node.id, parent_of, {b: ln.amount for b, ln in lines.items()})
            if has_children
            else payload.amount
        )
        self._check_line(node, payload, amount)
        amounts: dict[UUID, Decimal] = {
            **{bid: line.amount for bid, line in lines.items()},
            node.id: amount,
        }
        raised = plan_rules.summed_ancestors(node.id, parent_of, amounts, top.id)
        before = str(previous.amount) if previous is not None else None
        _assign(
            self._line_for(version.id, node.id, lines),
            amount=amount,
            note=payload.note,
            transferable=payload.transferable,
            coverable=payload.coverable,
            blocked=payload.blocked,
        )
        self._set_ancestors(version.id, raised, lines)
        await self._audit(
            AuditAction.BUDGET_PLAN_LINE_SET,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
                "versionId": str(version.id),
                "number": version.number,
                "budgetId": str(node.id),
                "amount": str(amount),
                "previousAmount": before,
                "raised": {str(k): str(v) for k, v in raised.items()},
            },
        )
        return await self._plan_out(plan, top.id)

    def _set_ancestors(
        self, version_id: UUID, sums: dict[UUID, Decimal], lines: dict[UUID, BudgetPlanLine]
    ) -> None:
        """Write the summed Ansatz of each ancestor. A blocked amount falls with it."""
        for ancestor_id, total in sums.items():
            line = self._line_for(version_id, ancestor_id, lines)
            _assign(line, amount=total, blocked=min(line.blocked, total))

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
        raised = plan_rules.summed_ancestors(
            budget_id,
            {n.id: n.parent_id for n in nodes},
            {bid: ln.amount for bid, ln in lines.items() if bid != budget_id},
            top.id,
        )
        self._set_ancestors(version.id, raised, lines)
        await self.session.delete(line)
        await self._audit(
            AuditAction.BUDGET_PLAN_LINE_SET,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
                "versionId": str(version.id),
                "number": version.number,
                "budgetId": str(budget_id),
                "amount": None,
                "previousAmount": str(line.amount),
                "raised": {str(k): str(v) for k, v in raised.items()},
            },
        )
        return await self._plan_out(plan, top.id)

    def _require_balanced(
        self, top: Budget, nodes: list[Budget], amounts: dict[UUID, Decimal]
    ) -> None:
        """Refuse a version whose income Ansätze differ from its expense Ansätze.

        Raises:
            ValidationProblem: `plan_not_balanced` (422).
        """
        direct = [(n.side, amounts.get(n.id, _ZERO)) for n in nodes if n.parent_id == top.id]
        if plan_rules.is_balanced(direct):
            return
        income, expense = plan_rules.side_sums(direct)
        raise ValidationProblem(
            "The plan is not balanced.",
            code="plan_not_balanced",
            errors=[{"field": "state", "msg": f"income {income} differs from expenses {expense}"}],
        )

    @staticmethod
    def _keep_names(lines: list[BudgetPlanLine], nodes: list[Budget]) -> None:
        """Write the current name and path key of each cost center into its line."""
        names = {n.id: (n.name, n.path_key) for n in nodes}
        for line in lines:
            _assign(line, name=names[line.budget_id][0], path_key=names[line.budget_id][1])

    async def _open_step(
        self, version: BudgetPlanVersion, top: Budget
    ) -> tuple[list[dict[str, Any]], int]:
        """Return the steps of a version and the index of its next step.

        A draft takes the steps of its budget and leaves the draft with this call:
        the version must be balanced, and each line keeps the name and the path key
        of its cost center.

        Raises:
            ConflictError: `plan_state_invalid` (409) for a version in force or
                replaced, `plan_no_step_left` (409) when the version has no step that
                is not passed.
            ValidationProblem: `plan_not_balanced` (422) for a draft.
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
            self._require_balanced(top, nodes, {line.budget_id: line.amount for line in lines})
            self._keep_names(lines, nodes)
        return steps, index

    async def pass_next_step(self, version_id: UUID, *, by_vote: UUID | None = None) -> PlanOut:
        """Record the next step of a version as passed.

        The first step takes the version out of the draft (`_open_step`).

        Raises:
            NotFoundError: The version does not exist (404).
            ConflictError: `fiscal_year_closed` (409), `plan_state_invalid` (409),
                `plan_no_step_left` (409).
            ValidationProblem: `plan_not_balanced` (422) at the first step.
        """
        version, plan, fy, top = await self._version_context(version_id)
        steps, index = await self._open_step(version, top)
        _assign(
            version,
            state="in_progress",
            steps=plan_rules.with_step_passed(steps, index, datetime.now(UTC).isoformat()),
        )
        await self._audit(
            AuditAction.BUDGET_PLAN_STEP,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
                "fiscalYearId": str(fy.id),
                "versionId": str(version.id),
                "number": version.number,
                "step": steps[index]["name"],
                "gremiumId": steps[index]["gremiumId"],
                "voteId": str(by_vote) if by_vote else None,
            },
        )
        return await self._plan_out(plan, top.id)

    async def _vote_runs(self, vote_id: str | None) -> bool:
        """Say if the vote of a step is a draft or open, so the step waits for it."""
        status = (
            await self.session.scalar(select(Vote.status).where(Vote.id == UUID(vote_id)))
            if vote_id
            else None
        )
        return status in ("draft", "open")

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
        vote_id = uuid.uuid4()
        _assign(
            version,
            state="in_progress",
            steps=plan_rules.with_step_vote(steps, index, str(vote_id)),
        )
        await self._audit(
            AuditAction.BUDGET_PLAN_STEP_VOTE,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
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

    async def pass_step_by_vote(self, version_id: UUID, vote_id: UUID) -> bool:
        """Pass the next step of a version for its accepted vote, and say if it did.

        The close of the vote calls this in its own transaction. The call passes
        nothing when the vote is not the vote of the next step (the version went back
        to draft, or the step was passed by hand) or when the fiscal year is closed,
        because the close of a vote must not fail for the state of the plan.
        """
        version = await self.session.get(BudgetPlanVersion, version_id)
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
        the allocations. A version that moves back to draft loses its passed steps.

        Raises:
            NotFoundError: The version does not exist (404).
            ConflictError: `fiscal_year_closed` (409), `plan_state_invalid` (409).
            ValidationProblem: `plan_not_balanced` (422) for a draft that comes into
                force.
        """
        version, plan, fy, top = await self._version_context(version_id)
        current = version.state
        target = payload.state
        lines = await self._lines(version.id)
        match target:
            case "in_force":
                steps = (
                    await self._budget_step_records(top.id)
                    if current == "draft"
                    else list(version.steps or [])
                )
                if not plan_rules.can_enter_force(current, steps):
                    raise ConflictError(
                        "The version has a step that is not passed.", code="plan_state_invalid"
                    )
                nodes = await self._subtree(top)
                amounts = {line.budget_id: line.amount for line in lines}
                if current == "draft":
                    self._require_balanced(top, nodes, amounts)
                    self._keep_names(lines, nodes)
                await self._replace_in_force(plan.id)
                _assign(version, in_force_at=datetime.now(UTC))
                await self._write_allocations(fy.id, top, nodes, amounts)
            case "draft":
                if not plan_rules.can_return_to_draft(current):
                    raise ConflictError(
                        f"A version in {current!r} cannot move back to draft.",
                        code="plan_state_invalid",
                    )
                _assign(version, steps=[])
                for line in lines:
                    _assign(line, name=None, path_key=None)
            case _:  # pragma: no cover
                assert_never(target)
        _assign(version, state=target)
        await self._audit(
            AuditAction.BUDGET_PLAN_STATE,
            target_type="budget_plan",
            target_id=str(plan.id),
            data={
                "fiscalYearId": str(fy.id),
                "versionId": str(version.id),
                "number": version.number,
                "before": current,
                "after": target,
            },
        )
        return await self._plan_out(plan, top.id)

    async def create_plan_node(self, version_id: UUID, payload: PlanNodeCreate) -> PlanOut:
        """Create a cost center and its line in a draft version, in one transaction.

        Raises:
            NotFoundError: The version or the parent does not exist (404).
            ConflictError: `fiscal_year_closed` (409), `plan_version_not_draft` (409),
                `budget_key_exists` (409).
            ValidationProblem: `plan_line_node_invalid` (422) for a parent outside
                the tree of the plan, `plan_side_missing` (422) for a direct child of
                the budget without a side.
        """
        version, _plan, _fy, top = await self._version_context(version_id)
        if version.state != "draft":
            raise ConflictError(
                "A cost centre is created only in a draft version.",
                code="plan_version_not_draft",
            )
        parent = next((n for n in await self._subtree(top) if n.id == payload.parent_id), None)
        if parent is None:
            await self._get_node(payload.parent_id)
            raise ValidationProblem(
                "The parent is not in the tree of this plan.",
                code="plan_line_node_invalid",
                errors=[{"field": "parentId", "msg": "not in the tree of the plan"}],
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
        await self._audit(
            AuditAction.BUDGET_NODE_CREATE,
            target_type="budget",
            target_id=str(node.id),
            data={"pathKey": node.path_key, "gremiumId": None, "decisionGremiumId": None},
        )
        await self.session.flush()
        return await self.set_line(version.id, node.id, PlanLineSet(amount=payload.amount))

    async def _replace_in_force(self, plan_id: UUID) -> None:
        """Set the version in force of a plan to replaced, before a new one takes over.

        The flush keeps the unique index on the version in force satisfied.
        """
        for earlier in await self._versions(plan_id):
            if earlier.state == "in_force":
                _assign(earlier, state="replaced")
        await self.session.flush()

    async def _write_allocations(
        self,
        fiscal_year_id: UUID,
        top: Budget,
        nodes: list[Budget],
        amounts: dict[UUID, Decimal],
    ) -> None:
        """Write the allocation of each cost center from the plan that comes into force."""
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
        for node in nodes:
            row = existing.get(node.id)
            if row is None:
                self.session.add(
                    BudgetAllocation(
                        id=uuid.uuid4(),
                        budget_id=node.id,
                        fiscal_year_id=fiscal_year_id,
                        allocated=target[node.id],
                    )
                )
            else:
                _assign(row, allocated=target[node.id])
