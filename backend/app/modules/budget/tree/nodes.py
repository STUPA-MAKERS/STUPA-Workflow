"""Cost-center (node) CRUD, including a key rename with a subtree path rewrite."""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import select

from app.modules.admin.models import Gremium
from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.budget import tree_rules
from app.modules.budget.tree.service_base import BudgetTreeServiceBase, _json_safe
from app.modules.budget.tree_models import Budget, BudgetExpense
from app.modules.budget.tree_rules import _SEP
from app.modules.budget.tree_schemas import BudgetNodeCreate, BudgetNodeOut, BudgetNodeUpdate
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem


def _node_out(b: Budget) -> BudgetNodeOut:
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
        acceptedStateKeys=list(b.accepted_state_keys or []),
        deniedStateKeys=list(b.denied_state_keys or []),
        hiddenInBudget=bool(b.hidden_in_budget),
        viewGremiumId=b.view_gremium_id,
        fiscalStartMonth=b.fiscal_start_month,
        fiscalStartDay=b.fiscal_start_day,
    )


class NodeOps(BudgetTreeServiceBase):
    """Create, update (with key rename) and delete cost-center nodes."""

    async def create_node(self, payload: BudgetNodeCreate) -> BudgetNodeOut:
        """Create a cost center. A child inherits the Gremium of its parent."""
        if not tree_rules.is_valid_key(payload.key):
            raise ValidationProblem(
                "Invalid budget key.",
                errors=[{"field": "key", "msg": "must be alphanumeric (no '-')"}],
            )

        if payload.parent_id is None:
            # A budget is not bound to a Gremium. The service validates the
            # optional gremiumId only when it is set. The flow decides who votes
            # and when, not the budget.
            if payload.gremium_id is not None:
                gremium = (
                    await self.session.execute(
                        select(Gremium).where(Gremium.id == payload.gremium_id)
                    )
                ).scalar_one_or_none()
                if gremium is None:
                    raise NotFoundError(f"gremium {payload.gremium_id} not found")
            parent_path = None
            gremium_id = payload.gremium_id
        else:
            parent = await self._get_node(payload.parent_id)
            parent_path = parent.path_key
            gremium_id = parent.gremium_id

        if await self._sibling_exists(payload.parent_id, payload.key):
            raise ConflictError(f"budget key {payload.key!r} already exists under this parent")

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
            # The fiscal start date counts only on the top level. A child keeps
            # the defaults.
            fiscal_start_month=payload.fiscal_start_month,
            fiscal_start_day=payload.fiscal_start_day,
        )
        self.session.add(node)
        await self._audit(
            AuditAction.BUDGET_NODE_CREATE,
            target_type="budget",
            target_id=str(node.id),
            data={
                "pathKey": node.path_key,
                "gremiumId": str(gremium_id) if gremium_id else None,
            },
        )
        await self.session.commit()
        return _node_out(node)

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
        """
        node = await self._get_node(budget_id)
        provided = payload.model_dump(exclude_unset=True)
        new_key = provided.pop("key", None)
        stichtag_changed = (
            "fiscal_start_month" in provided
            and provided["fiscal_start_month"] != node.fiscal_start_month
        ) or (
            "fiscal_start_day" in provided and provided["fiscal_start_day"] != node.fiscal_start_day
        )
        # Capture the prior values of the changed fields for audit-log revert.
        before: dict[str, object] = {
            field: _json_safe(getattr(node, field)) for field in provided
        }
        if new_key is not None:
            before["key"] = node.key
        for field, value in provided.items():
            setattr(node, field, value)
        if new_key is not None and new_key != node.key:
            await self._rename_key(node, new_key)
        if stichtag_changed and node.parent_id is None:
            for fy in await self._fiscal_years_of(budget_id):
                fy.start_date, fy.end_date = self._fiscal_year_bounds(
                    fy.year, node.fiscal_start_month, node.fiscal_start_day
                )
        # Capture the new values too. Revert uses them to detect a later edit
        # and answers 409 instead of overwriting the changes of another user.
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
        await self.session.commit()
        return _node_out(node)

    async def _rename_key(self, node: Budget, new_key: str) -> None:
        """Rename the `key` of a node and re-derive the `path_key` of its subtree.

        Raises:
            ValidationProblem: The new key segment is invalid (422).
            ConflictError: A sibling already uses the key (409).
        """
        if not tree_rules.is_valid_key(new_key):
            raise ValidationProblem(
                "Invalid budget key.",
                errors=[{"field": "key", "msg": "must be alphanumeric (no '-')"}],
            )
        if await self._sibling_exists(node.parent_id, new_key):
            raise ConflictError(f"budget key {new_key!r} already exists under this parent")
        parent_path: str | None = None
        if node.parent_id is not None:
            parent_path = (await self._get_node(node.parent_id)).path_key
        old_path = node.path_key
        new_path = tree_rules.compose_path_key(parent_path, new_key)
        # Fetch the descendants by path prefix before the rename of the node.
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
        node = await self._get_node(budget_id)
        child = (
            await self.session.execute(
                select(Budget.id).where(Budget.parent_id == budget_id).limit(1)
            )
        ).scalar_one_or_none()
        if child is not None:
            raise ConflictError("budget has child cost-centers; delete them first")
        booking = (
            await self.session.execute(
                select(BudgetExpense.id).where(BudgetExpense.budget_id == budget_id).limit(1)
            )
        ).scalar_one_or_none()
        if booking is not None:
            raise ConflictError("budget has bookings; remove them first")
        assigned = (
            await self.session.execute(
                select(Application.id).where(Application.budget_id == budget_id).limit(1)
            )
        ).scalar_one_or_none()
        if assigned is not None:
            raise ConflictError(
                "budget has assigned applications; reassign them first"
            )
        await self._audit(
            AuditAction.BUDGET_NODE_DELETE,
            target_type="budget",
            target_id=str(budget_id),
            data={"pathKey": node.path_key},
        )
        await self.session.delete(node)
        await self.session.commit()
