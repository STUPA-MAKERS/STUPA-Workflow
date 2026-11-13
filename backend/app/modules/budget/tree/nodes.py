"""Cost-center (node) CRUD, including a key rename with a subtree path rewrite."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.budget import plan_rules, tree_rules
from app.modules.budget.decision import decision_gremium_of
from app.modules.budget.plan_models import BudgetPlan, BudgetPlanLine, BudgetPlanVersion
from app.modules.budget.plan_rules import Side
from app.modules.budget.tree.service_base import (
    BudgetTreeServiceBase,
    _json_safe,
    _subtree_ids,
)
from app.modules.budget.tree_models import Budget, BudgetExpense, FiscalYear
from app.modules.budget.tree_rules import _SEP
from app.modules.budget.tree_schemas import BudgetNodeCreate, BudgetNodeOut, BudgetNodeUpdate
from app.modules.gremien.models import Gremium
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem


def _node_out(
    b: Budget, decision: tuple[UUID | None, UUID | None] = (None, None)
) -> BudgetNodeOut:
    """Map a node to its API shape.

    `decision` is the effective deciding Gremium and the node that holds it (see
    `NodeOps._decision_view`).
    """
    return BudgetNodeOut(
        id=b.id,
        parentId=b.parent_id,
        gremiumId=b.gremium_id,
        key=b.key,
        pathKey=b.path_key,
        name=b.name,
        currency=b.currency,
        active=b.active,
        color=b.color,
        viewGremiumId=b.view_gremium_id,
        decisionGremiumId=b.decision_gremium_id,
        effectiveDecisionGremiumId=decision[0],
        decisionGremiumSourceId=decision[1],
        fiscalStartMonth=b.fiscal_start_month,
        fiscalStartDay=b.fiscal_start_day,
        side=cast("Side | None", b.side),
        planEnabled=bool(b.plan_enabled),
    )

#: Fixed advisory-lock key of the keys of the top-level budgets (``"BUDGET_K"``).
_TOP_KEYS_LOCK = 0x4255444745545F4B



class NodeOps(BudgetTreeServiceBase):
    """Create, update (with key rename) and delete cost-center nodes."""

    async def _subtree(self, top: Budget) -> list[Budget]:
        """Return `top` and every node below it."""
        return list(
            (await self.session.scalars(select(Budget).where(Budget.id.in_(_subtree_ids(top)))))
            .all()
        )

    async def _lines(self, version_id: UUID) -> list[BudgetPlanLine]:
        return list(
            (
                await self.session.scalars(
                    select(BudgetPlanLine).where(BudgetPlanLine.version_id == version_id)
                )
            ).all()
        )

    @staticmethod
    def _resum(
        lines: Sequence[BudgetPlanLine], parent_of: Mapping[UUID, UUID | None]
    ) -> dict[UUID, Decimal]:
        """Give each parent among `lines` the sum of its children, and return the changes.

        `lines` are the lines that stay in the version. A blocked amount of a parent
        falls with its Ansatz.

        Raises:
            ValidationProblem: `plan_amount_too_large` (422) when a sum passes the
                largest amount that the database holds.
        """
        amounts = {line.budget_id: line.amount for line in lines}
        sums = plan_rules.summed_amounts(parent_of, amounts)
        if any(total > plan_rules.MAX_AMOUNT for total in sums.values()):
            raise ValidationProblem(
                "The sum of the child cost centres is above the largest amount.",
                code="plan_amount_too_large",
                errors=[{"field": "amount", "msg": "the sum of a parent is too large"}],
            )
        changed = {bid: total for bid, total in sums.items() if total != amounts[bid]}
        for line in lines:
            if line.budget_id in changed:
                total = changed[line.budget_id]
                line.amount = total
                line.blocked = min(line.blocked, total)
        return changed

    async def _leave_drafts(self, node: Budget) -> list[dict[str, object]]:
        """Take a cost center that goes away out of the sums of each draft version.

        Returns the removed line and the changed parents of each draft, as audit data.

        The delete of the node removes its plan lines through the foreign key. Each
        parent of a draft version then holds the sum of the children that stay.

        Raises:
            ConflictError: `fiscal_year_closed` (409) when a draft with a line of the
                node belongs to a closed fiscal year, because a closed year does not
                change.
        """
        versions = (
            await self.session.scalars(
                select(BudgetPlanVersion)
                .join(BudgetPlanLine, BudgetPlanLine.version_id == BudgetPlanVersion.id)
                .where(BudgetPlanLine.budget_id == node.id, BudgetPlanVersion.state == "draft")
            )
        ).all()
        if not versions:
            return []
        parent_of = {n.id: n.parent_id for n in await self._subtree(await self._top_level(node))}
        return [await self._leave_draft(node, version, parent_of) for version in versions]

    async def _leave_draft(
        self, node: Budget, version: BudgetPlanVersion, parent_of: Mapping[UUID, UUID | None]
    ) -> dict[str, object]:
        """Take the line of `node` out of one draft, and return the change as audit data."""
        plan = await self.session.get_one(BudgetPlan, version.plan_id)
        self._refuse_closed(await self._get_fiscal_year(plan.fiscal_year_id))
        lines = await self._lines(version.id)
        own = next(line for line in lines if line.budget_id == node.id)
        lowered = self._resum([ln for ln in lines if ln.budget_id != node.id], parent_of)
        return {
            "versionId": str(version.id),
            "previousAmount": f"{own.amount:.2f}",
            "lowered": {str(bid): f"{total:.2f}" for bid, total in lowered.items()},
        }

    async def _check_gremium(
        self, gremium_id: UUID | None, field: Literal["decisionGremiumId", "viewGremiumId"]
    ) -> None:
        """Refuse a deciding or a viewing Gremium that does not exist.

        Raises:
            ValidationProblem: `decision_gremium_invalid` or `view_gremium_invalid`
                (422).
        """
        if gremium_id is None:
            return
        found = await self.session.scalar(select(Gremium.id).where(Gremium.id == gremium_id))
        if found is None:
            raise ValidationProblem(
                f"{field} is not the id of a Gremium.",
                code=(
                    "decision_gremium_invalid"
                    if field == "decisionGremiumId"
                    else "view_gremium_invalid"
                ),
                errors=[{"field": field, "msg": "unknown gremium"}],
            )

    async def _lock_top_keys(self) -> None:
        """Take the lock of the keys of the top-level budgets until the commit.

        The top-level budgets have no common parent row to lock, so a fixed advisory
        lock stands in for it. A request takes it after the lock of its tree and
        before the audit log.
        """
        await self.session.execute(select(func.pg_advisory_xact_lock(_TOP_KEYS_LOCK)))

    @staticmethod
    def _flush_error(exc: IntegrityError, key: str) -> Exception:
        """Name the error of a flush that writes a key.

        Only the two unique constraints of the key mean a key that a sibling has.
        Any other error stays the error of the database, because a 409 for the key
        would name a wrong cause, for example for a Gremium that went away.
        """
        if "uq_budget_" not in str(exc.orig):
            return exc
        return ConflictError(
            f"budget key {key!r} already exists under this parent",
            code="budget_key_exists",
        )

    async def _decision_view(self, node: Budget) -> tuple[UUID | None, UUID | None]:
        """Return the effective deciding Gremium of `node` and the node that holds it.

        The own value wins. Otherwise the parent chain decides. The method reads the
        parent chain from the database, so it does not depend on a flush of `node`.
        """
        if node.decision_gremium_id is not None:
            return node.decision_gremium_id, node.id
        if node.parent_id is None:
            return None, None
        return await decision_gremium_of(self.session, node.parent_id)

    async def create_node(self, payload: BudgetNodeCreate) -> BudgetNodeOut:
        """Create a cost center. A child inherits the Gremium of its parent.

        A budget is not bound to a Gremium, because the flow decides who votes and when,
        not the budget. The optional ``gremiumId`` of a top-level node is validated only
        when it is set. The fiscal start date counts only on the top level. A child
        keeps the defaults.
        """
        if not tree_rules.is_valid_key(payload.key):
            raise ValidationProblem(
                "Invalid budget key.",
                errors=[{"field": "key", "msg": "must be alphanumeric (no '-')"}],
            )

        await self._lock_tree(payload.parent_id)
        if payload.parent_id is None:
            await self._lock_top_keys()
        parent = await self._get_node(payload.parent_id) if payload.parent_id is not None else None
        if parent is None and payload.gremium_id is not None:
            gremium = (
                await self.session.execute(
                    select(Gremium).where(Gremium.id == payload.gremium_id)
                )
            ).scalar_one_or_none()
            if gremium is None:
                raise NotFoundError(f"gremium {payload.gremium_id} not found")
        parent_path = parent.path_key if parent is not None else None
        gremium_id = parent.gremium_id if parent is not None else payload.gremium_id

        if await self._sibling_exists(payload.parent_id, payload.key):
            raise ConflictError(
                f"budget key {payload.key!r} already exists under this parent",
                code="budget_key_exists",
            )
        await self._check_gremium(payload.decision_gremium_id, "decisionGremiumId")
        direct = parent is not None and parent.parent_id is None
        if payload.side is not None and not direct:
            raise ValidationProblem(
                "The side is set on a direct child of a top-level cost centre.",
                code="side_not_settable",
                errors=[{"field": "side", "msg": "not a direct child of the top level"}],
            )
        side = payload.side if direct else (parent.side if parent is not None else None)
        if direct and parent is not None and parent.plan_enabled and side is None:
            raise ValidationProblem(
                "A cost centre directly below a budget with a Haushaltsplan needs a side.",
                code="plan_side_missing",
                errors=[{"field": "side", "msg": "the cost centre has no side"}],
            )

        node = Budget(
            id=uuid.uuid4(),
            parent_id=payload.parent_id,
            gremium_id=gremium_id,
            key=payload.key,
            path_key=tree_rules.compose_path_key(parent_path, payload.key),
            name=payload.name,
            currency=payload.currency,
            active=payload.active,
            color=payload.color,
            decision_gremium_id=payload.decision_gremium_id,
            fiscal_start_month=payload.fiscal_start_month,
            fiscal_start_day=payload.fiscal_start_day,
            side=side,
        )
        self.session.add(node)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise self._flush_error(exc, payload.key) from exc
        await self._audit(
            AuditAction.BUDGET_NODE_CREATE,
            target_type="budget",
            target_id=str(node.id),
            data={
                "pathKey": node.path_key,
                "gremiumId": str(gremium_id) if gremium_id else None,
                "decisionGremiumId": (
                    str(payload.decision_gremium_id) if payload.decision_gremium_id else None
                ),
            },
        )
        decision = await self._decision_view(node)
        await self.session.commit()
        return _node_out(node, decision)

    async def _sibling_exists(self, parent_id: UUID | None, key: str) -> bool:
        existing = (
            await self.session.execute(
                select(Budget).where(
                    Budget.parent_id.is_(parent_id)
                    if parent_id is None
                    else Budget.parent_id == parent_id,
                    Budget.key == key,
                )
            )
        ).scalar_one_or_none()
        return existing is not None

    async def update_node(self, budget_id: UUID, payload: BudgetNodeUpdate) -> BudgetNodeOut:
        """Update the name, the active flag, the fiscal start date or the key.

        The parent stays immutable to keep the tree stable. A new `key`
        re-derives the `path_key` of the node and of every descendant.
        Everything else references `budget_id`, not the path. A new fiscal start
        date on a top-level budget re-derives the start and end date of every
        existing fiscal year. The year stays and the dates follow.

        The audit entry holds the prior and the new values of the changed fields. The
        revert uses the new values to detect a later edit and answers 409 instead of
        overwriting the changes of another user.
        """
        await self._lock_tree(budget_id)
        node = await self._get_node(budget_id)
        dumped = payload.model_dump(exclude_unset=True)
        new_key = dumped.get("key")
        provided = {field: value for field, value in dumped.items() if field != "key"}
        if "decision_gremium_id" in provided:
            await self._check_gremium(provided["decision_gremium_id"], "decisionGremiumId")
        if "view_gremium_id" in provided:
            await self._check_gremium(provided["view_gremium_id"], "viewGremiumId")
        stichtag_changed = (
            "fiscal_start_month" in provided
            and provided["fiscal_start_month"] != node.fiscal_start_month
        ) or (
            "fiscal_start_day" in provided and provided["fiscal_start_day"] != node.fiscal_start_day
        )
        before: dict[str, object] = {
            **{field: _json_safe(getattr(node, field)) for field in provided},
            **({"key": node.key} if new_key is not None else {}),
        }
        for field, value in provided.items():
            setattr(node, field, value)
        if new_key is not None and new_key != node.key:
            await self._rename_key(node, new_key)
        if stichtag_changed and node.parent_id is None:
            for fy in await self._fiscal_years_of(budget_id):
                fy.start_date, fy.end_date = self._fiscal_year_bounds(
                    fy.year, node.fiscal_start_month, node.fiscal_start_day
                )
        after: dict[str, object] = {
            field: _json_safe(getattr(node, field)) for field in before
        }
        await self._audit(
            AuditAction.BUDGET_NODE_UPDATE,
            target_type="budget",
            target_id=str(node.id),
            data={
                "fields": sorted(provided),
                "keyProvided": new_key is not None,
                "before": before,
                "after": after,
            },
        )
        decision = await self._decision_view(node)
        await self.session.commit()
        return _node_out(node, decision)

    async def _rename_key(self, node: Budget, new_key: str) -> None:
        """Rename the `key` of a node and re-derive the `path_key` of its subtree.

        The descendants are fetched by path prefix before the node is renamed.

        Two top-level budgets share no lock of a tree, so a top-level budget takes
        the lock of the top-level keys before the check of its siblings. Without it
        two budgets with Kostenstellen that take one key at the same moment each
        write a part of the path keys and then wait for the other. The flush comes
        before the audit entry, so a wait for the unique index never holds the lock
        of the audit log.

        Raises:
            ValidationProblem: The new key segment is invalid (422).
            ConflictError: A sibling already uses the key (409).
        """
        if not tree_rules.is_valid_key(new_key):
            raise ValidationProblem(
                "Invalid budget key.",
                errors=[{"field": "key", "msg": "must be alphanumeric (no '-')"}],
            )
        if node.parent_id is None:
            await self._lock_top_keys()
        if await self._sibling_exists(node.parent_id, new_key):
            raise ConflictError(
                f"budget key {new_key!r} already exists under this parent",
                code="budget_key_exists",
            )
        parent_path = (
            (await self._get_node(node.parent_id)).path_key if node.parent_id is not None else None
        )
        old_path = node.path_key
        new_path = tree_rules.compose_path_key(parent_path, new_key)
        descendants = (
            (
                await self.session.execute(
                    select(Budget).where(Budget.path_key.like(old_path + _SEP + "%"))
                )
            )
            .scalars()
            .all()
        )
        node.key = new_key
        node.path_key = new_path
        for d in descendants:
            d.path_key = new_path + d.path_key[len(old_path) :]
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise self._flush_error(exc, new_key) from exc

    async def _plans_of_top(self, node: Budget) -> dict[str, object]:
        """Return the plans that go with a top-level budget, as audit data.

        The delete of a budget takes its fiscal years and their plans along by the
        foreign key, so the entry names each plan with its year and its versions.
        """
        if node.parent_id is not None:
            return {}
        rows = (
            await self.session.execute(
                select(BudgetPlan.id, FiscalYear.year, BudgetPlanVersion.id)
                .join(FiscalYear, FiscalYear.id == BudgetPlan.fiscal_year_id)
                .join(BudgetPlanVersion, BudgetPlanVersion.plan_id == BudgetPlan.id)
                .where(FiscalYear.budget_id == node.id)
                .order_by(FiscalYear.year, BudgetPlanVersion.number)
            )
        ).all()
        plans = {
            plan_id: {
                "planId": str(plan_id),
                "year": year,
                "versionIds": [str(v) for p, _y, v in rows if p == plan_id],
            }
            for plan_id, year, _version in rows
        }
        return {"deletedPlans": list(plans.values())} if plans else {}

    async def delete_node(self, budget_id: UUID) -> None:
        """Delete a cost center.

        The delete fails with 409 only for data that must not get lost or
        orphaned. This covers child cost centers, bookings on this center, and
        applications still assigned to it. The `BudgetAllocation` rows of the
        node hold only planning figures, that is the available sum per fiscal
        year. The FK cascade removes them together with the node. They are
        deliberately no reason to refuse the delete. Otherwise a childless leaf
        that ever had an allocation could never be deleted. A reset to 0 keeps
        the row, and no separate action removes an allocation.
        """
        await self._lock_tree(budget_id)
        node = await self._get_node(budget_id)
        child = (
            await self.session.execute(
                select(Budget.id).where(Budget.parent_id == budget_id).limit(1)
            )
        ).scalar_one_or_none()
        if child is not None:
            raise ConflictError(
                "budget has child cost-centers; delete them first",
                code="budget_has_children",
            )
        booking = (
            await self.session.execute(
                select(BudgetExpense.id).where(BudgetExpense.budget_id == budget_id).limit(1)
            )
        ).scalar_one_or_none()
        if booking is not None:
            raise ConflictError(
                "budget has bookings; remove them first",
                code="budget_has_bookings",
            )
        assigned = (
            await self.session.execute(
                select(Application.id).where(Application.budget_id == budget_id).limit(1)
            )
        ).scalar_one_or_none()
        if assigned is not None:
            raise ConflictError(
                "budget has assigned applications; reassign them first",
                code="budget_has_applications",
            )
        planned = (
            await self.session.execute(
                select(BudgetPlanLine.id)
                .join(BudgetPlanVersion, BudgetPlanVersion.id == BudgetPlanLine.version_id)
                .where(BudgetPlanLine.budget_id == budget_id, BudgetPlanVersion.state != "draft")
                .limit(1)
            )
        ).scalar_one_or_none()
        if planned is not None:
            raise ConflictError(
                "budget is part of a decided Haushaltsplan",
                code="budget_in_plan",
            )
        left = await self._leave_drafts(node)
        await self._audit(
            AuditAction.BUDGET_NODE_DELETE,
            target_type="budget",
            target_id=str(budget_id),
            data={
                "pathKey": node.path_key,
                "name": node.name,
                "draftLines": left,
                **await self._plans_of_top(node),
            },
        )
        await self.session.delete(node)
        await self.session.commit()
