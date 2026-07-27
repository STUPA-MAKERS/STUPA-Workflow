"""Application to cost-center assignment and subtree application listing."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select

from app.modules.applications.models import Application
from app.modules.applications.service.service_base import _title_of
from app.modules.audit.actions import AuditAction
from app.modules.budget.models import BudgetEntry
from app.modules.budget.tree.service_base import BudgetTreeServiceBase
from app.modules.budget.tree_models import Budget
from app.modules.budget.tree_rules import _SEP
from app.modules.budget.tree_schemas import (
    AssignBudgetOut,
    AssignBudgetRequest,
    BudgetApplicationOut,
    MoveFiscalYearRequest,
)
from app.modules.flow.models import State
from app.shared.errors import NotFoundError, ValidationProblem


class AssignmentOps(BudgetTreeServiceBase):
    """Assign applications to cost centers and fiscal years, and list them."""

    async def _get_application(self, application_id: UUID) -> Application:
        app = (
            await self.session.execute(select(Application).where(Application.id == application_id))
        ).scalar_one_or_none()
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        return app

    async def list_applications(
        self, budget_id: UUID, fiscal_year_id: UUID | None = None
    ) -> list[BudgetApplicationOut]:
        """List the applications of this cost center **and of its subtree**.

        The subtree comes from the ``path_key`` prefix: the node itself (``==``)
        or a descendant (``LIKE path||'-%'``). ``stage`` comes from the
        ``budget_entry``, which is 1:1 per application. An optional fiscal year
        filters the result. The newest application comes first.
        """
        node = await self._get_node(budget_id)
        subtree = select(Budget.id).where(
            or_(
                Budget.path_key == node.path_key,
                Budget.path_key.like(node.path_key + _SEP + "%"),
            )
        )
        stmt = (
            select(
                Application,
                Budget.path_key,
                BudgetEntry.stage,
                State.label_i18n,
                State.color,
            )
            .join(Budget, Budget.id == Application.budget_id)
            .outerjoin(BudgetEntry, BudgetEntry.application_id == Application.id)
            .outerjoin(State, State.id == Application.current_state_id)
            .where(Application.budget_id.in_(subtree))
            .order_by(Application.created_at.desc())
        )
        if fiscal_year_id is not None:
            stmt = stmt.where(Application.fiscal_year_id == fiscal_year_id)
        rows = (await self.session.execute(stmt)).all()
        return [
            BudgetApplicationOut(
                applicationId=app.id,
                title=_title_of(app.data),
                budgetId=app.budget_id,
                pathKey=path_key,
                fiscalYearId=app.fiscal_year_id,
                amount=app.amount,
                currency=app.currency,
                stage=stage,
                stateId=app.current_state_id,
                stateLabel=state_label or None,
                stateColor=state_color,
                createdAt=app.created_at,
            )
            for (app, path_key, stage, state_label, state_color) in rows
        ]

    async def assign_budget(
        self, application_id: UUID, payload: AssignBudgetRequest
    ) -> AssignBudgetOut:
        """Assign an application to a cost center.

        ``budgetId=null`` clears the assignment. ``fiscalYearId`` then becomes
        null as well.

        With a cost center set, ``_resolve_fiscal_year`` picks the fiscal year.
        An explicit ``fiscalYearId`` must belong to the top-level budget. Without
        one, the method takes the single open active fiscal year.

        Raises:
            ValidationProblem: The fiscal year is ambiguous or missing. The
                method fails with a 422 instead of leaving ``fiscal_year_id``
                NULL. This mirrors the behavior of bookings.
        """
        app = await self._get_application(application_id)
        if payload.budget_id is None:
            app.budget_id = None
            app.fiscal_year_id = None
            await self._audit(
                AuditAction.BUDGET_ASSIGN,
                target_type="application",
                target_id=str(app.id),
                data={"budgetId": None, "fiscalYearId": None},
            )
            await self.session.commit()
            return AssignBudgetOut(applicationId=app.id, budgetId=None, fiscalYearId=None)

        node = await self._get_node(payload.budget_id)
        fy_id = await self._resolve_fiscal_year(node, payload.fiscal_year_id)
        app.budget_id = node.id
        app.fiscal_year_id = fy_id
        await self._audit(
            AuditAction.BUDGET_ASSIGN,
            target_type="application",
            target_id=str(app.id),
            data={"budgetId": str(node.id), "fiscalYearId": str(fy_id)},
        )
        await self.session.commit()
        return AssignBudgetOut(applicationId=app.id, budgetId=node.id, fiscalYearId=fy_id)

    async def move_fiscal_year(
        self, application_id: UUID, payload: MoveFiscalYearRequest
    ) -> AssignBudgetOut:
        """Move an application to another fiscal year of its top-level budget.

        Raises:
            ValidationProblem: The application has no budget assignment, or the
                fiscal year belongs to another top-level budget.
        """
        app = await self._get_application(application_id)
        if app.budget_id is None:
            raise ValidationProblem(
                "Application has no budget assignment.",
                errors=[{"field": "budgetId", "msg": "assign a cost-center first"}],
            )
        node = await self._get_node(app.budget_id)
        top = await self._top_level(node)
        fy = await self._get_fiscal_year(payload.fiscal_year_id)
        if fy.budget_id != top.id:
            raise ValidationProblem(
                "Fiscal year does not belong to this application's top-level budget.",
                errors=[{"field": "fiscalYearId", "msg": "wrong top-level budget"}],
            )
        app.fiscal_year_id = fy.id
        await self._audit(
            AuditAction.BUDGET_MOVE_FISCAL_YEAR,
            target_type="application",
            target_id=str(app.id),
            data={"budgetId": str(app.budget_id), "fiscalYearId": str(fy.id)},
        )
        await self.session.commit()
        return AssignBudgetOut(applicationId=app.id, budgetId=app.budget_id, fiscalYearId=fy.id)
