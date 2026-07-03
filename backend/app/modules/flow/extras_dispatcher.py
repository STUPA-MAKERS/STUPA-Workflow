"""Flow action handlers for ``addToNextSession`` and ``assignBudget``.

``addToNextSession`` appends the application as an agenda item to the earliest
upcoming meeting of the given gremium (logged + skipped if none exists);
``assignBudget`` attaches a cost centre and derives the fiscal year from the
single active one of the top-level node. Per-action errors are logged, never
propagated — a failed action must not roll back the committed state change.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget.tree_models import Budget, FiscalYear
from app.modules.flow.dispatch import DispatchedAction
from app.modules.livevote.agenda_service import AgendaService
from app.modules.livevote.models import Meeting
from app.shared.errors import ConflictError, NotFoundError

logger = logging.getLogger("app.flow.actions")

# Actor recorded for money mutations performed by the flow engine itself (no human
# principal in scope on a transition's side-effect). Mirrors the house rule that all
# budget mutations leave an audit trail (see BudgetTreeService.assign_budget).
_FLOW_ACTOR = "system:flow"


@dataclass(slots=True)
class FlowExtrasActionDispatcher:
    """``ActionDispatcher`` for ``addToNextSession`` + ``assignBudget`` (else no-op)."""

    sessionmaker: async_sessionmaker[AsyncSession]

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        for action in actions:
            try:
                if action.type == "addToNextSession":
                    await self._add_to_next_session(action)
                elif action.type == "assignBudget":
                    await self._assign_budget(action)
                elif action.type == "assignBudgetFromField":
                    await self._assign_budget_from_field(action)
            except Exception:  # noqa: BLE001 — an action failure must not undo the
                # committed state change nor block the transition's remaining actions.
                logger.exception(
                    "flow action %s failed (key=%s) — skipped",
                    action.type,
                    action.idempotency_key,
                )

    # ---------------------------------------------------------- addToNextSession
    async def _add_to_next_session(self, action: DispatchedAction) -> None:
        gremium_ref = action.params.get("gremiumId")
        if not gremium_ref:
            logger.warning("addToNextSession without 'gremiumId' — skipped")
            return
        try:
            gremium_id = UUID(str(gremium_ref))
        except ValueError:
            logger.warning("addToNextSession invalid gremiumId %r — skipped", gremium_ref)
            return
        today = datetime.now(UTC).date()
        async with self.sessionmaker() as session:
            meeting = await session.scalar(
                select(Meeting)
                .where(
                    Meeting.gremium_id == gremium_id,
                    Meeting.date.is_not(None),
                    Meeting.date >= today,
                    Meeting.status != "finalized",
                )
                .order_by(Meeting.date.asc(), Meeting.start_time.asc().nullslast())
                .limit(1)
            )
            if meeting is None:
                logger.warning(
                    "addToNextSession: no upcoming meeting for gremium %s — skipped",
                    gremium_id,
                )
                return
            try:
                await AgendaService(session).add(
                    meeting.id, application_id=action.application_id
                )
            except (NotFoundError, ConflictError) as exc:
                logger.warning(
                    "addToNextSession: could not add application %s to meeting %s: %s",
                    action.application_id,
                    meeting.id,
                    exc,
                )

    # --------------------------------------------------------------- assignBudget
    async def _assign_budget(self, action: DispatchedAction) -> None:
        budget_id = _parse_budget_uuid("assignBudget", action.params.get("budgetId"))
        if budget_id is None:
            return
        await self._do_assign(action.application_id, budget_id, source="flow")

    # ------------------------------------------------------ assignBudgetFromField
    async def _assign_budget_from_field(self, action: DispatchedAction) -> None:
        """Assign the cost centre chosen in a form field (e.g. ``gremium_select``/
        ``budget_select``) — one dynamic pick collapses many fixed triage edges into one.
        """
        field = action.params.get("field")
        if not field:
            logger.warning("assignBudgetFromField without 'field' — skipped")
            return
        async with self.sessionmaker() as session:
            app = await session.get(Application, action.application_id)
            if app is None:
                logger.warning(
                    "assignBudgetFromField: application %s missing — skipped",
                    action.application_id,
                )
                return
            raw = app.data.get(str(field)) if isinstance(app.data, dict) else None
            budget_id = _parse_budget_uuid(f"assignBudgetFromField field {field!r}", raw)
            if budget_id is None:
                return
            if await self._assign_node(session, app, budget_id, source="flow:field"):
                await session.commit()

    async def _do_assign(
        self, application_id: UUID, budget_id: UUID, *, source: str
    ) -> None:
        async with self.sessionmaker() as session:
            app = await session.get(Application, application_id)
            if app is None:
                logger.warning("assignBudget: application %s missing — skipped", application_id)
                return
            if await self._assign_node(session, app, budget_id, source=source):
                await session.commit()

    async def _assign_node(
        self, session: AsyncSession, app: Application, budget_id: UUID, *, source: str
    ) -> bool:
        """Assign the cost centre + its single active fiscal year and write the audit.

        ``True`` when assigned (caller commits), ``False`` when the node is missing
        (nothing mutated)."""
        node = await session.get(Budget, budget_id)
        if node is None:
            logger.warning("assignBudget: budget %s missing — skipped", budget_id)
            return False
        app.budget_id = node.id
        top = await self._top_level(session, node)
        active_ids = (
            await session.scalars(
                select(FiscalYear.id).where(
                    FiscalYear.budget_id == top.id,
                    FiscalYear.active.is_(True),
                )
            )
        ).all()
        # Set only an unambiguous active fiscal year; otherwise leave open.
        if len(active_ids) == 1:
            app.fiscal_year_id = active_ids[0]
        # Money mutation -> audit trail (house rule; mirrors BudgetTreeService).
        await audit_record(
            session,
            actor=_FLOW_ACTOR,
            action=AuditAction.BUDGET_ASSIGN,
            target_type="application",
            target_id=str(app.id),
            data={
                "budgetId": str(app.budget_id),
                "fiscalYearId": (
                    str(app.fiscal_year_id) if app.fiscal_year_id is not None else None
                ),
                "source": source,
            },
        )
        return True

    @staticmethod
    async def _top_level(session: AsyncSession, node: Budget) -> Budget:
        """Walk the parent chain to the top-level node (``parent_id IS NULL``)."""
        current = node
        seen: set[UUID] = set()
        while current.parent_id is not None and current.parent_id not in seen:
            seen.add(current.id)
            parent = await session.get(Budget, current.parent_id)
            if parent is None:
                break
            current = parent
        return current


def _parse_budget_uuid(label: str, ref: object) -> UUID | None:
    """Parse a budget reference to ``UUID``; empty/invalid -> log + ``None`` (fail-closed).

    A value read from a form field may be missing or garbage — then the application stays
    without a cost centre (the budget guard is itself fail-closed)."""
    if not ref:
        logger.warning("%s: empty budget reference — skipped", label)
        return None
    try:
        return UUID(str(ref))
    except ValueError:
        logger.warning("%s: invalid budget id %r — skipped", label, ref)
        return None


def build_flow_extras_dispatcher(pool: object) -> FlowExtrasActionDispatcher:
    """Build the dispatcher for app wiring; needs no arq pool."""
    return FlowExtrasActionDispatcher(get_sessionmaker())
