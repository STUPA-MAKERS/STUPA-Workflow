"""Read one version of a Haushaltsplan for a file (§F/finance/budget/000875)."""

from __future__ import annotations

from collections.abc import Collection
from datetime import date
from uuid import UUID

from sqlalchemy import select

from app.modules.budget import plan_rules, tree_rules
from app.modules.budget.plan_export import (
    ExportHead,
    PlanExport,
    PlanFile,
    build_export,
    plan_file,
    plan_file_of,
)
from app.modules.budget.plan_models import (
    BudgetPlan,
    BudgetPlanStep,
    BudgetPlanVersion,
    BudgetPlanVoteSnapshot,
)
from app.modules.budget.plan_schemas import (
    PlanLineOut,
    PlanOut,
    PlanVersionOut,
    WaitingPlanOut,
)
from app.modules.budget.tree.plans import PlanOps
from app.modules.budget.tree.view import TreeViewOps
from app.modules.budget.tree_models import Budget, FiscalYear
from app.modules.files.cd_resolver import ResolvedCdVariant, resolve_cd_variant_of_gremium
from app.shared.errors import ForbiddenError, NotFoundError


def _before(plan: PlanOut, version: PlanVersionOut) -> tuple[PlanLineOut, ...]:
    """Return the lines of the version with the next lower number, else none."""
    older = [v for v in plan.versions if v.number < version.number]
    return max(older, key=lambda v: v.number).lines if older else ()


def _in_force(plan: PlanOut | None) -> tuple[PlanLineOut, ...]:
    """Return the lines of the version in force of a plan, else none."""
    versions = plan.versions if plan is not None else ()
    return next((v.lines for v in versions if v.state == "in_force"), ())


def _decided(plan: PlanOut | None) -> bool:
    """Say if a plan has a version in force."""
    return plan is not None and any(v.state == "in_force" for v in plan.versions)


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
        plan_before = await self._plan_in(before)
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
            prev_decided=_decided(plan_before),
        )
        return build_export(
            head,
            top,
            version.lines,
            base=_before(plan, version),
            prev=_in_force(plan_before),
            prev_fiscal_year_id=before.id if before else None,
        )

    async def keep_vote_snapshot(self, version_id: UUID, vote_id: UUID, today: date) -> None:
        """Keep the file of a version as it is when a vote on it opens (spec 000876).

        A vote that opens again replaces its file.

        Raises:
            NotFoundError: The version does not exist (404).
        """
        export = await self.plan_export(version_id, today)
        await self.session.merge(
            BudgetPlanVoteSnapshot(vote_id=vote_id, document=plan_file(export).record)
        )
        await self.session.flush()

    async def plan_file_for_protocol(
        self, version_id: UUID | None, vote_ids: Collection[UUID], today: date
    ) -> PlanFile | None:
        """Return the file of a version as the protocol of a meeting appends it.

        A vote among ``vote_ids`` that kept a file gives the file of the vote that
        opened last, so a later change or the delete of the draft does not reach the
        protocol. Without one, the version gives its state of now.

        Returns:
            The file, or ``None`` when no vote kept one and ``version_id`` is ``None``.
        """
        kept = (
            await self.session.scalars(
                select(BudgetPlanVoteSnapshot.document)
                .where(BudgetPlanVoteSnapshot.vote_id.in_(vote_ids))
                .order_by(BudgetPlanVoteSnapshot.created_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if kept is not None:
            return plan_file_of(kept)
        return (
            plan_file(await self.plan_export(version_id, today))
            if version_id is not None
            else None
        )

    def _reading_out(
        self, version: BudgetPlanVersion, fy: FiscalYear, top: Budget
    ) -> WaitingPlanOut:
        year = tree_rules.fiscal_year_display(fy.year, top.fiscal_start_month, top.fiscal_start_day)
        return WaitingPlanOut(
            planVersionId=version.id,
            budgetName=top.name,
            fiscalYear=year,
            number=version.number,
            step=plan_rules.READING,
            title=plan_rules.step_title(top.name, year, version.number, plan_rules.READING),
            reading=True,
        )

    async def _drafts(
        self, version_id: UUID | None = None
    ) -> list[tuple[BudgetPlanVersion, FiscalYear, Budget]]:
        rows = (
            await self.session.execute(
                select(BudgetPlanVersion, FiscalYear, Budget)
                .join(BudgetPlan, BudgetPlan.id == BudgetPlanVersion.plan_id)
                .join(FiscalYear, FiscalYear.id == BudgetPlan.fiscal_year_id)
                .join(Budget, Budget.id == FiscalYear.budget_id)
                .where(
                    BudgetPlanVersion.state == "draft",
                    FiscalYear.closed_at.is_(None),
                    Budget.plan_enabled.is_(True),
                    *([BudgetPlanVersion.id == version_id] if version_id is not None else []),
                )
                .order_by(Budget.name, FiscalYear.year, BudgetPlanVersion.number)
            )
        ).all()
        return [(version, fy, top) for version, fy, top in rows]

    async def plan_budget_ids(self, gremium_id: UUID) -> frozenset[UUID]:
        """Return the budgets with a plan that this Gremium decides in a step (spec 000876)."""
        return frozenset(
            await self.session.scalars(
                select(BudgetPlanStep.budget_id)
                .join(Budget, Budget.id == BudgetPlanStep.budget_id)
                .where(BudgetPlanStep.gremium_id == gremium_id, Budget.plan_enabled.is_(True))
            )
        )

    async def reading_plans(
        self, gremium_id: UUID, member_gremium_ids: set[UUID] | None
    ) -> list[WaitingPlanOut]:
        """List the drafts that an agenda of this Gremium can take for a reading (spec 000876).

        These are the drafts of the budgets whose plan the Gremium decides in a step.
        ``member_gremium_ids`` is ``None`` for a person with the full view of the
        budgets. Any other person gets the drafts of the budgets that the Gremien give
        a view of.
        """
        decided = await self.plan_budget_ids(gremium_id)
        visible = (
            None
            if member_gremium_ids is None
            else await self.visible_budget_ids(member_gremium_ids)
        )
        return [
            self._reading_out(version, fy, top)
            for version, fy, top in await self._drafts()
            if top.id in decided and (visible is None or top.id in visible)
        ]

    async def reading_plan(
        self, version_id: UUID, gremium_id: UUID, member_gremium_ids: set[UUID] | None
    ) -> WaitingPlanOut | None:
        """Return a draft that this person can put on an agenda of this Gremium for a reading.

        Returns:
            The draft, or ``None`` when the version is no draft of an open year, or the
            Gremium decides the plan of its budget in no step.

        Raises:
            ForbiddenError: The person cannot read the budget of the draft (403).
        """
        found = await self._drafts(version_id)
        if not found:
            return None
        version, fy, top = found[0]
        if top.id not in await self.plan_budget_ids(gremium_id):
            return None
        if member_gremium_ids is not None and top.id not in await self.visible_budget_ids(
            member_gremium_ids
        ):
            raise ForbiddenError("no access to this cost centre")
        return self._reading_out(version, fy, top)
