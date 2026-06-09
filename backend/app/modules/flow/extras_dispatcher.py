"""Flow-Action-Handler ``addToNextSession`` + ``assignBudget`` (#28).

Erfüllt das T-14-Dispatch-Interface für die beiden Aktionen, die der Flow direkt auf
Sitzungs-/Budget-Daten ausführt (kein Mail-/Webhook-Versand):

* ``addToNextSession`` — den Antrag als TOP an die **nächste** (früheste zukünftige)
  Sitzung des angegebenen Gremiums hängen. Existiert keine, wird geloggt + übersprungen
  (Action ist nur auf Übergängen **in einen vote-State** zulässig — vom Graph-Validator
  erzwungen, ``config_schemas``).
* ``assignBudget`` — dem Antrag eine Kostenstelle (Budget-Baum) zuordnen; das
  Haushaltsjahr wird aus dem **einzigen aktiven** HHJ des Top-Level-Knotens abgeleitet.

Fehler je Action werden geloggt, nicht propagiert — eine fehlgeschlagene Action darf den
bereits committeten State-Wechsel nicht zurücknehmen (flows §9.3, idempotent/retrybar).
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
from app.modules.budget.tree_models import Budget, FiscalYear
from app.modules.flow.dispatch import DispatchedAction
from app.modules.livevote.agenda_service import AgendaService
from app.modules.livevote.models import Meeting
from app.shared.errors import ConflictError, NotFoundError

logger = logging.getLogger("app.flow.actions")


@dataclass(slots=True)
class FlowExtrasActionDispatcher:
    """`ActionDispatcher` für ``addToNextSession`` + ``assignBudget`` (sonst No-op)."""

    sessionmaker: async_sessionmaker[AsyncSession]

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        for action in actions:
            if action.type == "addToNextSession":
                await self._add_to_next_session(action)
            elif action.type == "assignBudget":
                await self._assign_budget(action)

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
        budget_ref = action.params.get("budgetId")
        if not budget_ref:
            logger.warning("assignBudget without 'budgetId' — skipped")
            return
        try:
            budget_id = UUID(str(budget_ref))
        except ValueError:
            logger.warning("assignBudget invalid budgetId %r — skipped", budget_ref)
            return
        async with self.sessionmaker() as session:
            app = await session.get(Application, action.application_id)
            node = await session.get(Budget, budget_id)
            if app is None or node is None:
                logger.warning(
                    "assignBudget: application %s or budget %s missing — skipped",
                    action.application_id,
                    budget_id,
                )
                return
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
            # Eindeutiges aktives HHJ → setzen; sonst offen lassen (mehrdeutig/keins).
            if len(active_ids) == 1:
                app.fiscal_year_id = active_ids[0]
            await session.commit()

    @staticmethod
    async def _top_level(session: AsyncSession, node: Budget) -> Budget:
        """Den Top-Level-Knoten (``parent_id IS NULL``) über die Eltern-Kette finden."""
        current = node
        seen: set[UUID] = set()
        while current.parent_id is not None and current.parent_id not in seen:
            seen.add(current.id)
            parent = await session.get(Budget, current.parent_id)
            if parent is None:
                break
            current = parent
        return current


def build_flow_extras_dispatcher(pool: object) -> FlowExtrasActionDispatcher:
    """Dispatcher fürs App-Wiring (main.py). Braucht keinen arq-Pool."""
    return FlowExtrasActionDispatcher(get_sessionmaker())
