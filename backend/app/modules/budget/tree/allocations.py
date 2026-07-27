"""Top-down allocations with parent/children constraints."""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, select

from app.modules.audit.actions import AuditAction
from app.modules.budget import tree_rules
from app.modules.budget.tree.service_base import _ZERO, BudgetTreeServiceBase
from app.modules.budget.tree_models import Budget, BudgetAllocation
from app.modules.budget.tree_schemas import AllocationOut, AllocationSet
from app.shared.errors import ValidationProblem


class AllocationOps(BudgetTreeServiceBase):
    """Set per-fiscal-year allocations under pessimistic locking."""

    async def _allocation(self, budget_id: UUID, fiscal_year_id: UUID) -> BudgetAllocation | None:
        return (
            await self.session.execute(
                select(BudgetAllocation).where(
                    BudgetAllocation.budget_id == budget_id,
                    BudgetAllocation.fiscal_year_id == fiscal_year_id,
                )
            )
        ).scalar_one_or_none()

    async def _lock_budget(self, budget_id: UUID) -> None:
        """Lock the budget row pessimistically (``SELECT … FOR UPDATE``).

        The lock serializes concurrent sibling allocations. They all lock the
        same parent row. Read-sum, validate and write then stay atomic, so no
        double over-allocation gets through.
        """
        await self.session.execute(
            select(Budget.id).where(Budget.id == budget_id).with_for_update()
        )

    async def _children_alloc_sum(
        self, parent_id: UUID, fiscal_year_id: UUID, *, exclude_id: UUID | None = None
    ) -> Decimal:
        rows = (
            await self.session.execute(
                select(Budget.id, BudgetAllocation.allocated)
                .join(
                    BudgetAllocation,
                    and_(
                        BudgetAllocation.budget_id == Budget.id,
                        BudgetAllocation.fiscal_year_id == fiscal_year_id,
                    ),
                )
                .where(Budget.parent_id == parent_id)
            )
        ).all()
        total = _ZERO
        for child_id, allocated in rows:
            if child_id != exclude_id:
                total += tree_rules.as_amount(allocated)
        return total

    async def set_allocation(
        self, budget_id: UUID, fiscal_year_id: UUID, payload: AllocationSet
    ) -> AllocationOut:
        """Set a top-down allocation.

        Raises:
            ValidationProblem: The fiscal year belongs to another top-level
                budget, the children sum exceeds the parent allocation, or the
                new allocation falls below the sum already given to children.
        """
        node = await self._get_node(budget_id)
        fy = await self._get_fiscal_year(fiscal_year_id)
        top = await self._top_level(node)
        if fy.budget_id != top.id:
            raise ValidationProblem(
                "Fiscal year does not belong to this budget's top-level.",
                errors=[{"field": "fiscalYearId", "msg": "wrong top-level budget"}],
            )

        # Lock BEFORE read, validate and write to stay race-free. The own row
        # guards the downward constraint against the own children. The parent row
        # serializes all concurrent sibling allocations. Both then read the same
        # already locked sibling sum and cannot overbook together.
        await self._lock_budget(node.id)
        if node.parent_id is not None:
            await self._lock_budget(node.parent_id)

        # Upward constraint: new children sum ≤ parent allocation.
        if node.parent_id is not None:
            siblings = await self._children_alloc_sum(
                node.parent_id, fiscal_year_id, exclude_id=node.id
            )
            parent_alloc = await self._allocation(node.parent_id, fiscal_year_id)
            parent_value = parent_alloc.allocated if parent_alloc is not None else None
            if tree_rules.children_allocation_exceeds_parent(
                parent_value, siblings, payload.allocated
            ):
                raise ValidationProblem(
                    "Children allocation would exceed the parent budget.",
                    errors=[{"field": "allocated", "msg": "exceeds parent budget"}],
                )

        # Downward constraint: allocation not below the sum already given to children.
        own_children = await self._children_alloc_sum(node.id, fiscal_year_id)
        if tree_rules.parent_allocation_below_children(payload.allocated, own_children):
            raise ValidationProblem(
                "Allocation is below the sum already distributed to children.",
                errors=[{"field": "allocated", "msg": "below children allocations"}],
            )

        alloc = await self._allocation(budget_id, fiscal_year_id)
        # Remember the prior value for the audit-log revert. It is ``None`` on the
        # first set.
        previous_allocated = (
            str(alloc.allocated)
            if alloc is not None and alloc.allocated is not None
            else None
        )
        if alloc is None:
            alloc = BudgetAllocation(
                id=uuid.uuid4(),
                budget_id=budget_id,
                fiscal_year_id=fiscal_year_id,
            )
            self.session.add(alloc)
        alloc.allocated = payload.allocated
        await self._audit(
            AuditAction.BUDGET_ALLOCATION_SET,
            target_type="budget_allocation",
            target_id=str(budget_id),
            data={
                "fiscalYearId": str(fiscal_year_id),
                "allocated": str(payload.allocated),
                "previousAllocated": previous_allocated,
            },
        )
        await self.session.commit()
        return AllocationOut(
            budgetId=budget_id,
            fiscalYearId=fiscal_year_id,
            allocated=payload.allocated,
        )
