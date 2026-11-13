"""Shared base of the `service.BudgetTreeService` ops classes.

It holds the constructor plus the lookup and audit helpers that several concerns
need: nodes, fiscal years, allocations, bookings, transfers and revert. The
decision logic lives in `app.modules.budget.tree_rules`. Errors surface as
problem+json.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Select, or_, select

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget import tree_rules
from app.modules.budget.access import viewed_by
from app.modules.budget.tree_models import Budget, FiscalYear
from app.modules.budget.tree_rules import _SEP
from app.settings import Settings, get_settings
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.files.storage import ObjectStorage

_ZERO = Decimal(0)


def _json_safe(value: object) -> object:
    """Make a prior-state value for audit and revert JSON-serializable.

    The function stores money, date and id values as strings. `Decimal`, `date`,
    `datetime` and `UUID` therefore survive in the audit `data` without loss. On
    revert Pydantic coerces the strings back into typed patch fields.

    A ``datetime`` takes the ``date`` branch, because it is a subclass of ``date``.
    """
    match value:
        case Decimal() | UUID():
            return str(value)
        case date():
            return value.isoformat()
        case _:
            return value


def _applied(*clauses: ColumnElement[bool] | None) -> tuple[ColumnElement[bool], ...]:
    """Keep the filter clauses that a request sets, in order.

    `None` stands for a filter that the request leaves out. The test is `is not None`,
    because the truth value of a SQL clause is undefined.
    """
    return tuple(clause for clause in clauses if clause is not None)


def _subtree_ids(node: Budget) -> Select[UUID]:
    """Select the ids of `node` and of every node below it, by the path-key prefix."""
    return select(Budget.id).where(
        or_(
            Budget.path_key == node.path_key,
            Budget.path_key.like(node.path_key + _SEP + "%"),
        )
    )


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
        """Bind the service to a session.

        Only the invoice import needs ``storage`` and ``settings``. The other budget
        endpoints leave them as None. ``actor`` is the principal ``sub`` for the audit
        trail of the money mutations. The router sets it, and an instance without an
        actor, as in tests, logs ``actor=None``.
        """
        self.session = session
        self.storage = storage
        self.settings = settings or get_settings()
        self.actor = actor

    async def _audit(
        self,
        action: AuditAction,
        *,
        target_type: str,
        target_id: str,
        data: dict[str, Any] | None = None,
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

    async def visible_budget_ids(self, member_gremium_ids: set[UUID]) -> set[UUID]:
        """Return the ids of the cost centres that a gremium-scoped reader may see.

        A node is visible when a member Gremium reads the node itself or an ancestor
        (`access.viewed_by`). This is the set form of `TreeViewOps.can_view_node`: the
        matching root paths open their whole subtree through the ``path_key`` prefix.
        A holder of the full budget view needs no filter and does not call this.

        A path segment is alphanumeric (`tree_rules.is_valid_key`), so the prefix holds
        no LIKE wildcard.
        """
        if not member_gremium_ids:
            return set()
        root_paths = (
            await self.session.scalars(
                select(Budget.path_key).where(viewed_by(member_gremium_ids))
            )
        ).all()
        if not root_paths:
            return set()
        scoped = or_(
            *[
                or_(Budget.path_key == rp, Budget.path_key.like(f"{rp}{_SEP}%"))
                for rp in root_paths
            ]
        )
        return set((await self.session.scalars(select(Budget.id).where(scoped))).all())

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

    @staticmethod
    def _refuse_closed(fy: FiscalYear) -> None:
        """Refuse a money mutation on a closed fiscal year.

        Raises:
            ConflictError: `fiscal_year_closed` (409). The year must be reopened
                first.
        """
        if fy.closed_at is not None:
            raise ConflictError(
                "The fiscal year is closed. Reopen it to change its money data.",
                code="fiscal_year_closed",
            )

    async def _require_open_fiscal_year(self, fiscal_year_id: UUID | None) -> None:
        """Refuse a money mutation when the fiscal year is closed.

        `None` passes: an application without a fiscal year touches no year. A
        missing row passes too, because the foreign keys of bookings and
        applications keep the year in place, so there is nothing to freeze.

        Raises:
            ConflictError: `fiscal_year_closed` (409).
        """
        if fiscal_year_id is None:
            return
        fy = await self.session.get(FiscalYear, fiscal_year_id)
        if fy is not None:
            self._refuse_closed(fy)

    async def _lock_tree(self, budget_id: UUID | None) -> None:
        """Lock the top-level budget above a cost center, before a write in its tree.

        Each write in the tree of a budget takes this lock first: a write of a plan, and
        each write that a plan depends on or that reads what such a write changes (a
        cost center, a key, a side, an allocation, a fiscal year, the steps, the plan
        switch). Two writes on one budget then run one after the other, and the second
        reads what the first left: the statement reads the row of the budget again, so
        its plan switch is the one that the write before left. A caller reads its own
        rows after this lock, never before. The lock comes before the lock of a plan
        row and before the audit entry, so no two writes wait for each other.

        The statement finds the top level by the parent chain, because the parent of a
        cost center never changes and its path key can. The lock is `FOR NO KEY
        UPDATE`, because a new row that points at the budget (a booking, a line) must
        not wait for it. A cost center that does not exist locks no row.
        """
        if budget_id is None:
            return
        up = (
            select(Budget.id, Budget.parent_id)
            .where(Budget.id == budget_id)
            .cte("up", recursive=True)
        )
        chain = up.union_all(
            select(Budget.id, Budget.parent_id).where(Budget.id == up.c.parent_id)
        )
        top = select(chain.c.id).where(chain.c.parent_id.is_(None)).scalar_subquery()
        await self.session.execute(
            select(Budget)
            .where(Budget.id == top)
            .with_for_update(of=Budget, key_share=True)
            .execution_options(populate_existing=True)
        )

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

    async def _plan_for_new_year(self, top: Budget, fy: FiscalYear) -> None:
        """Give a new fiscal year what the plan of its budget needs.

        The plan operations replace this, because the fiscal year operations sit below
        them and cannot call them.
        """

    async def _resolve_fiscal_year(self, node: Budget, fiscal_year_id: UUID | None) -> UUID:
        """Resolve the fiscal year of a node operation.

        A booking, a transfer and an assignment all use this. An explicit fiscal
        year must belong to the top-level budget. Without one the method takes
        the current fiscal year of the top-level budget: the single active open
        year, or among several active open years the one that contains the
        local date. A closed year never counts as that default. The result is
        never `None`.

        Raises:
            ValidationProblem: The fiscal year belongs to another top-level
                budget, or no current fiscal year can be derived (422).
            ConflictError: `fiscal_year_closed` (409) for an explicit closed
                fiscal year.
        """
        top = await self._top_level(node)
        if fiscal_year_id is not None:
            fy = await self._get_fiscal_year(fiscal_year_id)
            if fy.budget_id != top.id:
                raise ValidationProblem(
                    "Fiscal year does not belong to this budget's top-level.",
                    errors=[{"field": "fiscalYearId", "msg": "wrong top-level budget"}],
                )
            self._refuse_closed(fy)
            return fy.id
        candidates = [
            (f.id, f.start_date, f.end_date)
            for f in await self._fiscal_years_of(top.id)
            if f.active and f.closed_at is None
        ]
        today = datetime.now(ZoneInfo(self.settings.local_timezone)).date()
        picked = tree_rules.pick_fiscal_year(candidates, today)
        if picked is None:
            raise ValidationProblem(
                "No current fiscal year — specify fiscalYearId.",
                errors=[{"field": "fiscalYearId", "msg": "ambiguous or missing"}],
            )
        return picked
