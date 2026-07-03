"""Fiscal-year CRUD and label map on top-level budgets."""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import select

from app.modules.budget import tree_rules
from app.modules.budget.tree.service_base import BudgetTreeServiceBase
from app.modules.budget.tree_models import Budget, FiscalYear
from app.modules.budget.tree_schemas import FiscalYearCreate, FiscalYearOut, FiscalYearUpdate
from app.shared.errors import ValidationProblem


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
        """Fiscal years for ANY node: non-top-level resolves to its top-level
        ancestor (scoped roots are often sub cost-centres)."""
        node = await self._get_node(budget_id)
        top = node
        while top.parent_id is not None:
            top = await self._get_node(top.parent_id)
        return [
            _fy_out(f, top.fiscal_start_month, top.fiscal_start_day)
            for f in await self._fiscal_years_of(top.id)
        ]

    async def fiscal_year_label_map(self) -> dict[UUID, str]:
        """``fiscal_year_id`` → display (``YYYY``/``YYYY/YY``) across all top budgets."""
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
        """Create a fiscal year — bounds derive from the budget's start date."""
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
        """Update year and/or active flag; the year stays unique per top budget."""
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
