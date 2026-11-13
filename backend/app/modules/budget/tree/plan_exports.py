"""Read one version of a Haushaltsplan for a file (§F/finance/budget/000875)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select

from app.modules.budget import tree_rules
from app.modules.budget.plan_export import ExportHead, PlanExport, build_export
from app.modules.budget.plan_schemas import PlanLineOut, PlanOut, PlanVersionOut
from app.modules.budget.tree.plans import PlanOps
from app.modules.budget.tree.view import TreeViewOps
from app.modules.budget.tree_models import Budget, FiscalYear
from app.modules.files.cd_resolver import ResolvedCdVariant, resolve_cd_variant_of_gremium
from app.shared.errors import NotFoundError


def _before(plan: PlanOut, version: PlanVersionOut) -> tuple[PlanLineOut, ...]:
    """Return the lines of the version with the next lower number, else none."""
    older = [v for v in plan.versions if v.number < version.number]
    return max(older, key=lambda v: v.number).lines if older else ()


def _in_force(plan: PlanOut | None) -> tuple[PlanLineOut, ...]:
    """Return the lines of the version in force of a plan, else none."""
    versions = plan.versions if plan is not None else ()
    return next((v.lines for v in versions if v.state == "in_force"), ())


def _open_step(version: PlanVersionOut) -> str | None:
    """Return the name of the first step that the version has not passed, else none."""
    return next((s.name for s in version.steps if s.passed_at is None), None)


class PlanExportOps(PlanOps, TreeViewOps):
    """Collect what the file of a plan version holds."""

    async def _year_before(self, fy: FiscalYear) -> FiscalYear | None:
        return (
            await self.session.scalars(
                select(FiscalYear).where(
                    FiscalYear.budget_id == fy.budget_id, FiscalYear.year == fy.year - 1
                )
            )
        ).one_or_none()

    async def _plan_in(self, fy: FiscalYear | None) -> PlanOut | None:
        plan = await self._plan_of(fy.id) if fy is not None else None
        return await self._plan_out(plan, fy.budget_id) if plan is not None and fy else None

    async def plan_design(self, version_id: UUID) -> ResolvedCdVariant | None:
        """Return the corporate design of the Gremium of the budget of a version.

        Returns:
            The design, or `None` when the budget has no Gremium or the Gremium no design.

        Raises:
            NotFoundError: The version does not exist (404).
            ServiceUnavailableError: An uploaded logo cannot be read (503).
        """
        plan = await self.plan_of_version(version_id)
        gremium_id = await self.session.scalar(
            select(Budget.gremium_id).where(Budget.id == plan.budget_id)
        )
        return await resolve_cd_variant_of_gremium(self.session, self.storage, gremium_id)

    async def plan_export(self, version_id: UUID, today: date) -> PlanExport:
        """Return a version of a Haushaltsplan as the rows of a file.

        The rows are those of the plan page: the lines in tree order, the version
        before for a Nachtrag, and the Ansatz and the booked amounts of the year
        before.

        Raises:
            NotFoundError: The version does not exist (404).
        """
        plan = await self.plan_of_version(version_id)
        version = next((v for v in plan.versions if v.id == version_id), None)
        top = next((n for n in await self.get_tree() if n.id == plan.budget_id), None)
        if version is None or top is None:
            raise NotFoundError(f"plan version {version_id} not found")
        fy = await self._get_fiscal_year(plan.fiscal_year_id)
        before = await self._year_before(fy)
        month, day = top.fiscal_start_month, top.fiscal_start_day
        head = ExportHead(
            budget_name=top.name,
            fiscal_year=tree_rules.fiscal_year_display(fy.year, month, day),
            prev_year=(
                tree_rules.fiscal_year_display(before.year, month, day) if before else None
            ),
            number=version.number,
            state=version.state,
            exported_on=today,
            step=_open_step(version),
        )
        return build_export(
            head,
            top,
            version.lines,
            base=_before(plan, version),
            prev=_in_force(await self._plan_in(before)),
            prev_fiscal_year_id=before.id if before else None,
        )
