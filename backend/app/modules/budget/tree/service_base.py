"""Shared base of the `service.BudgetTreeService` ops classes.

It holds the constructor plus the lookup and audit helpers that several concerns
need: nodes, fiscal years, allocations, bookings, transfers and revert. The
decision logic lives in `app.modules.budget.tree_rules`. Errors surface as
problem+json.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget import tree_rules
from app.modules.budget.tree_models import Budget, FiscalYear
from app.modules.budget.tree_rules import _SEP
from app.settings import Settings, get_settings
from app.shared.errors import NotFoundError, ValidationProblem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.files.storage import ObjectStorage

_ZERO = Decimal("0")


def _json_safe(value: object) -> object:
    """Make a prior-state value for audit and revert JSON-serializable.

    The function stores money, date and id values as strings. `Decimal`, `date`,
    `datetime` and `UUID` therefore survive in the audit `data` without loss. On
    revert Pydantic coerces the strings back into typed patch fields.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):  # also covers datetime, a subclass of date
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


class BudgetTreeServiceBase:
    """Shared base for cost-center tree operations, bound to one session."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: ObjectStorage | None = None,
        settings: Settings | None = None,
        actor: str | None = None,
    ) -> None:
        self.session = session
        # Only the invoice import needs storage and settings. The other budget
        # endpoints do not wire them and leave them as None.
        self.storage = storage
        self.settings = settings or get_settings()
        # Principal sub for the audit trail of money mutations. The router sets
        # it. A direct instance without an actor, as in tests, logs actor=None.
        self.actor = actor

    async def _audit(
        self,
        action: AuditAction,
        *,
        target_type: str,
        target_id: str,
        data: dict | None = None,
    ) -> None:
        """Write the audit entry inside the running transaction.

        The entry goes in before the mutation commits, so the mutation and the
        audit entry commit atomically. `data` takes id references and amounts
        only. It must carry no PII.
        """
        await audit_record(
            self.session,
            actor=self.actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            data=data or {},
        )

    async def _get_node(self, budget_id: UUID) -> Budget:
        node = (
            await self.session.execute(select(Budget).where(Budget.id == budget_id))
        ).scalar_one_or_none()
        if node is None:
            raise NotFoundError(f"budget {budget_id} not found")
        return node

    async def _get_fiscal_year(self, fiscal_year_id: UUID) -> FiscalYear:
        fy = (
            await self.session.execute(select(FiscalYear).where(FiscalYear.id == fiscal_year_id))
        ).scalar_one_or_none()
        if fy is None:
            raise NotFoundError(f"fiscal year {fiscal_year_id} not found")
        return fy

    async def _top_level(self, node: Budget) -> Budget:
        """Return the top-level budget of a node.

        It is the first path segment and holds `parent_id IS NULL`.
        """
        top_path = node.path_key.split(_SEP, 1)[0]
        top = (
            await self.session.execute(
                select(Budget).where(Budget.path_key == top_path, Budget.parent_id.is_(None))
            )
        ).scalar_one_or_none()
        if top is None:
            raise NotFoundError(f"top-level budget for {node.path_key!r} not found")
        return top

    async def _fiscal_years_of(self, budget_id: UUID) -> list[FiscalYear]:
        return list(
            (
                await self.session.execute(
                    select(FiscalYear)
                    .where(FiscalYear.budget_id == budget_id)
                    .order_by(FiscalYear.year)
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    def _fiscal_year_bounds(year: int, start_month: int, start_day: int) -> tuple[date, date]:
        """Derive the start and the end date of a fiscal year.

        The schemas already cap `fiscalStartDay` at 1 to 28. This wrapper is the
        defensive path for old rows and for direct service calls.

        Raises:
            ValidationProblem: The start date does not exist. The caller gets
                422 instead of 500.
        """
        try:
            return tree_rules.fiscal_year_bounds(year, start_month, start_day)
        except ValueError as exc:
            raise ValidationProblem(
                "Invalid fiscal year start date.",
                errors=[{"field": "fiscalStartDay", "msg": str(exc)}],
            ) from exc

    async def _resolve_fiscal_year(self, node: Budget, fiscal_year_id: UUID | None) -> UUID:
        """Resolve the fiscal year of a node operation.

        A booking, a transfer and an assignment all use this. An explicit fiscal
        year must belong to the top-level budget. Without one the method takes
        the single active fiscal year of the top-level budget. The result is
        never `None`.

        Raises:
            ValidationProblem: The fiscal year belongs to another top-level
                budget, or no single active fiscal year exists (422).
        """
        top = await self._top_level(node)
        if fiscal_year_id is not None:
            fy = await self._get_fiscal_year(fiscal_year_id)
            if fy.budget_id != top.id:
                raise ValidationProblem(
                    "Fiscal year does not belong to this budget's top-level.",
                    errors=[{"field": "fiscalYearId", "msg": "wrong top-level budget"}],
                )
            return fy.id
        active_ids = [f.id for f in await self._fiscal_years_of(top.id) if f.active]
        picked = tree_rules.pick_fiscal_year(active_ids)
        if picked is None:
            raise ValidationProblem(
                "No single active fiscal year — specify fiscalYearId.",
                errors=[{"field": "fiscalYearId", "msg": "ambiguous or missing"}],
            )
        return picked
