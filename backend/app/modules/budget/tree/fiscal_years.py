"""Fiscal-year CRUD and label map on top-level budgets."""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.budget import tree_rules
from app.modules.budget.tree.service_base import BudgetTreeServiceBase
from app.modules.budget.tree_models import Budget, BudgetAllocation, BudgetExpense, FiscalYear
from app.modules.budget.tree_schemas import FiscalYearCreate, FiscalYearOut, FiscalYearUpdate
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem


def _fy_out(f: FiscalYear, start_month: int, start_day: int) -> FiscalYearOut:
    return FiscalYearOut(
        id=f.id,
        budgetId=f.budget_id,
        year=f.year,
        display=tree_rules.fiscal_year_display(f.year, start_month, start_day),
        startDate=f.start_date,
        endDate=f.end_date,
        active=f.active,
    )


class FiscalYearOps(BudgetTreeServiceBase):
    """List, create and update fiscal years (unique per top-level budget)."""

    async def _require_top_level(self, budget_id: UUID) -> Budget:
        node = await self._get_node(budget_id)
        if node.parent_id is not None:
            raise ValidationProblem(
                "Fiscal years exist only on top-level budgets.",
                errors=[{"field": "budgetId", "msg": "not a top-level budget"}],
            )
        return node

    async def list_fiscal_years(self, budget_id: UUID) -> list[FiscalYearOut]:
        """List the fiscal years for any node.

        A node below the top level resolves to its top-level ancestor. A scoped
        root is often a sub cost center.
        """
        node = await self._get_node(budget_id)
        top = node
        while top.parent_id is not None:
            top = await self._get_node(top.parent_id)
        return [
            _fy_out(f, top.fiscal_start_month, top.fiscal_start_day)
            for f in await self._fiscal_years_of(top.id)
        ]

    async def fiscal_year_label_map(self) -> dict[UUID, str]:
        """Map every `fiscal_year_id` to its display label.

        The map covers all top-level budgets. A label reads `YYYY` or `YYYY/YY`.
        """
        rows = (
            await self.session.execute(
                select(
                    FiscalYear.id,
                    FiscalYear.year,
                    Budget.fiscal_start_month,
                    Budget.fiscal_start_day,
                ).join(Budget, Budget.id == FiscalYear.budget_id)
            )
        ).all()
        return {
            fid: tree_rules.fiscal_year_display(year, month, day) for fid, year, month, day in rows
        }

    async def create_fiscal_year(self, budget_id: UUID, payload: FiscalYearCreate) -> FiscalYearOut:
        """Create a fiscal year. Its bounds derive from the budget start date."""
        top = await self._require_top_level(budget_id)
        start, end = self._fiscal_year_bounds(
            payload.year, top.fiscal_start_month, top.fiscal_start_day
        )
        existing = await self._fiscal_years_of(budget_id)
        if any(f.year == payload.year for f in existing):
            raise ValidationProblem(
                "Fiscal year already exists for this budget.",
                errors=[{"field": "year", "msg": "fiscal year already exists"}],
            )
        fy = FiscalYear(
            id=uuid.uuid4(),
            budget_id=budget_id,
            year=payload.year,
            start_date=start,
            end_date=end,
            active=payload.active,
        )
        self.session.add(fy)
        await self.session.commit()
        return _fy_out(fy, top.fiscal_start_month, top.fiscal_start_day)

    async def update_fiscal_year(
        self, budget_id: UUID, fiscal_year_id: UUID, payload: FiscalYearUpdate
    ) -> FiscalYearOut:
        """Update the year or the active flag. A year stays unique per top budget."""
        top = await self._require_top_level(budget_id)
        fy = await self._get_fiscal_year(fiscal_year_id)
        provided = payload.model_dump(exclude_unset=True)
        new_year = provided.get("year", fy.year)
        if new_year != fy.year and any(
            f.year == new_year and f.id != fiscal_year_id
            for f in await self._fiscal_years_of(budget_id)
        ):
            raise ValidationProblem(
                "Fiscal year already exists for this budget.",
                errors=[{"field": "year", "msg": "fiscal year already exists"}],
            )
        if "year" in provided:
            fy.year = new_year
            fy.start_date, fy.end_date = self._fiscal_year_bounds(
                new_year, top.fiscal_start_month, top.fiscal_start_day
            )
        if "active" in provided:
            fy.active = provided["active"]
        await self.session.commit()
        return _fy_out(fy, top.fiscal_start_month, top.fiscal_start_day)

    async def _uses_fiscal_year(
        self,
        id_col: InstrumentedAttribute[UUID],
        fy_col: InstrumentedAttribute[UUID] | InstrumentedAttribute[UUID | None],
        fiscal_year_id: UUID,
    ) -> bool:
        """Tell whether at least one row of that table references this fiscal year."""
        found = (
            await self.session.execute(
                select(id_col).where(fy_col == fiscal_year_id).limit(1)
            )
        ).scalar_one_or_none()
        return found is not None

    async def delete_fiscal_year(self, budget_id: UUID, fiscal_year_id: UUID) -> None:
        """Delete a fiscal year of a top-level budget.

        The delete refuses with 409 while money still hangs on the year:
        bookings, allocations, or applications assigned to it. `budget_expense`
        and `budget_allocation` cascade on the foreign key, so an unguarded
        delete would drop them without a trace. `application.fiscal_year_id`
        has no cascade and would fail on the constraint. The guard mirrors
        `NodeOps.delete_node`, which refuses for the same reason.

        Raises:
            NotFoundError: The budget or the fiscal year does not exist, or the
                fiscal year belongs to another top-level budget (404).
            ValidationProblem: `budget_id` is not a top-level budget (422).
            ConflictError: Money rows still reference the fiscal year (409).
        """
        top = await self._require_top_level(budget_id)
        fy = await self._get_fiscal_year(fiscal_year_id)
        if fy.budget_id != top.id:
            raise NotFoundError(
                f"fiscal year {fiscal_year_id} does not belong to budget {budget_id}"
            )
        blocker = tree_rules.fiscal_year_delete_blocker(
            await self._uses_fiscal_year(
                BudgetExpense.id, BudgetExpense.fiscal_year_id, fiscal_year_id
            ),
            await self._uses_fiscal_year(
                BudgetAllocation.id, BudgetAllocation.fiscal_year_id, fiscal_year_id
            ),
            await self._uses_fiscal_year(
                Application.id, Application.fiscal_year_id, fiscal_year_id
            ),
        )
        if blocker is not None:
            raise ConflictError(
                f"fiscal year still has {blocker}; remove them first"
            )
        await self._audit(
            AuditAction.BUDGET_FISCAL_YEAR_DELETE,
            target_type="fiscal_year",
            target_id=str(fiscal_year_id),
            data={"budgetId": str(top.id), "year": fy.year},
        )
        await self.session.delete(fy)
        await self.session.commit()
