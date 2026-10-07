"""Flow action handlers for the agenda and the cost-center actions.

`addToNextSession` appends the application as an agenda item to the earliest meeting of
the given Gremium that is still `planned` and whose date is today or later in local time.
Without a `gremiumId` the handler takes the Gremium of the vote
(`application.vote_gremium_id`, set by the engine before the commit). A live or closed
meeting never gets the item. If no such meeting exists, the handler logs the case and
skips the action. `assignBudget` attaches a cost center. It derives the fiscal year from
the single active fiscal year of the top-level node. `assignBudgetFromField` does the
same with the cost center id that a form field holds. `assignBudgetFromApplicantGremium`
takes the single cost center whose own deciding Gremium is a Gremium of the applicant.
`assignBudgetFromMap` maps the value of a form field to a cost center. No cost-center
action changes the cost center while the application sits in a vote state whose
Gremium comes from the cost center.
The dispatcher logs an error of a single action and never propagates it. A failed action
must not roll back the committed state change.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget.tree_models import Budget, FiscalYear
from app.modules.budget.tree_rules import _SEP
from app.modules.flow.context import committee_ids_for_sub
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.vote_gremium import in_budget_vote_state
from app.modules.livevote.agenda_service import AgendaService
from app.modules.livevote.models import Meeting
from app.settings import get_settings
from app.shared.errors import ConflictError, NotFoundError

logger = logging.getLogger("app.flow.actions")

# Actor for the money mutations that the flow engine makes itself. A side effect of a
# transition has no human principal in scope. The house rule says that every budget
# mutation leaves an audit trail (see BudgetTreeService.assign_budget).
_FLOW_ACTOR = "system:flow"


@dataclass(slots=True)
class FlowExtrasActionDispatcher:
    """`ActionDispatcher` for the budget and agenda actions.

    It handles `addToNextSession`, `assignBudget` and `assignBudgetFromField`. Every
    other action type is a no-op.
    """

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
                elif action.type == "assignBudgetFromApplicantGremium":
                    await self._assign_budget_from_applicant_gremium(action)
                elif action.type == "assignBudgetFromMap":
                    await self._assign_budget_from_map(action)
            except Exception:  # noqa: BLE001 — an action failure must not undo the
                # committed state change nor block the transition's remaining actions.
                logger.exception(
                    "flow action %s failed (key=%s) — skipped",
                    action.type,
                    action.idempotency_key,
                )

    async def _add_to_next_session(self, action: DispatchedAction) -> None:
        # `Meeting.date` is a local calendar day, so compare it with the local date.
        # Only a `planned` meeting takes a new agenda item. A live or closed meeting
        # of today is not "the next session".
        today = datetime.now(ZoneInfo(get_settings().local_timezone)).date()
        async with self.sessionmaker() as session:
            gremium_id = await self._agenda_gremium(session, action)
            if gremium_id is None:
                return
            meeting = await session.scalar(
                select(Meeting)
                .where(
                    Meeting.gremium_id == gremium_id,
                    Meeting.date.is_not(None),
                    Meeting.date >= today,
                    Meeting.status == "planned",
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

    @staticmethod
    async def _agenda_gremium(
        session: AsyncSession, action: DispatchedAction
    ) -> UUID | None:
        """Return the Gremium of an `addToNextSession` action, or `None` to skip it.

        An explicit `gremiumId` wins. Without one the action takes the snapshot
        `application.vote_gremium_id`: the engine set it in the transaction of the
        state change, before this post-commit dispatch.
        """
        if "gremiumId" not in action.params:
            gremium_id = await session.scalar(
                select(Application.vote_gremium_id).where(
                    Application.id == action.application_id
                )
            )
            if gremium_id is None:
                logger.warning(
                    "addToNextSession: application %s has no vote Gremium — skipped",
                    action.application_id,
                )
            return gremium_id
        gremium_ref = action.params.get("gremiumId")
        if not gremium_ref:
            logger.warning("addToNextSession with an empty 'gremiumId' — skipped")
            return None
        try:
            return UUID(str(gremium_ref))
        except ValueError:
            logger.warning("addToNextSession invalid gremiumId %r — skipped", gremium_ref)
            return None

    async def _assign_budget_from_applicant_gremium(self, action: DispatchedAction) -> None:
        """Assign the single cost center that a Gremium of the applicant decides on.

        The candidates are the active nodes whose OWN `decision_gremium_id` (not an
        inherited one) is a Gremium where the applicant is a member now. An optional
        `parentId` limits the search to that node and its subtree. Exactly one
        candidate gets assigned. Zero or several candidates assign nothing and give a
        log line: a person then assigns the cost center by hand.
        """
        parent_ref = action.params.get("parentId")
        async with self.sessionmaker() as session:
            app = await session.get(Application, action.application_id)
            if app is None:
                logger.warning(
                    "assignBudgetFromApplicantGremium: application %s missing — skipped",
                    action.application_id,
                )
                return
            gremien = await _applicant_gremien(session, app.created_by)
            if not gremien:
                logger.info(
                    "assignBudgetFromApplicantGremium: applicant of %s has no Gremium — "
                    "nothing assigned",
                    app.id,
                )
                return
            stmt = select(Budget.id).where(
                Budget.active.is_(True), Budget.decision_gremium_id.in_(gremien)
            )
            if parent_ref:
                parent_id = _parse_budget_uuid(
                    "assignBudgetFromApplicantGremium parentId", parent_ref
                )
                parent_path = (
                    await session.scalar(
                        select(Budget.path_key).where(Budget.id == parent_id)
                    )
                    if parent_id is not None
                    else None
                )
                if parent_path is None:
                    logger.warning(
                        "assignBudgetFromApplicantGremium: parent %r missing — skipped",
                        parent_ref,
                    )
                    return
                stmt = stmt.where(
                    or_(
                        Budget.path_key == parent_path,
                        Budget.path_key.like(parent_path + _SEP + "%"),
                    )
                )
            matches = list((await session.scalars(stmt)).all())
            if len(matches) != 1:
                logger.info(
                    "assignBudgetFromApplicantGremium: %d matching cost centers for "
                    "application %s — nothing assigned",
                    len(matches),
                    app.id,
                )
                return
            if await self._assign_node(
                session, app, matches[0], source="flow:applicantGremium"
            ):
                await session.commit()

    async def _assign_budget_from_map(self, action: DispatchedAction) -> None:
        """Assign the cost center that `map` gives for the value of a form field.

        The admin maintains the map, so the target is always a curated node. A field
        value without an entry, an empty value or a list value assigns nothing.
        """
        field = action.params.get("field")
        mapping = action.params.get("map")
        if not field or not isinstance(mapping, dict):
            logger.warning("assignBudgetFromMap without 'field' or 'map' — skipped")
            return
        async with self.sessionmaker() as session:
            app = await session.get(Application, action.application_id)
            if app is None:
                logger.warning(
                    "assignBudgetFromMap: application %s missing — skipped",
                    action.application_id,
                )
                return
            raw = app.data.get(str(field)) if isinstance(app.data, dict) else None
            if raw is None or isinstance(raw, (list, dict)) or str(raw) not in mapping:
                logger.info(
                    "assignBudgetFromMap: no map entry for field %r of application %s — "
                    "nothing assigned",
                    field,
                    app.id,
                )
                return
            budget_id = _parse_budget_uuid(
                f"assignBudgetFromMap field {field!r}", mapping[str(raw)]
            )
            if budget_id is None:
                return
            if await self._assign_node(session, app, budget_id, source="flow:map"):
                await session.commit()

    async def _assign_budget(self, action: DispatchedAction) -> None:
        budget_id = _parse_budget_uuid("assignBudget", action.params.get("budgetId"))
        if budget_id is None:
            return
        await self._do_assign(action.application_id, budget_id, source="flow")

    async def _assign_budget_from_field(self, action: DispatchedAction) -> None:
        """Assign the cost center that a form field holds.

        The field is a picker such as `gremium_select` or `budget_select`. One dynamic
        pick replaces many fixed triage edges in the flow graph.

        The applicant controls the field value, so the handler accepts only the set that
        the form offered (see `FormService._budget_field_options`). It skips the action
        (fail closed) when the node is missing or inactive. It also does not overwrite a
        different cost center that the application already has, because a staff decision
        wins over an applicant value.
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
            node = await session.get(Budget, budget_id)
            if node is None or not node.active:
                logger.warning(
                    "assignBudgetFromField: budget %s missing or inactive — skipped",
                    budget_id,
                )
                return
            if app.budget_id is not None and app.budget_id != node.id:
                logger.warning(
                    "assignBudgetFromField: application %s already has budget %s — "
                    "no overwrite with %s",
                    app.id,
                    app.budget_id,
                    node.id,
                )
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
        """Assign the cost center and its single active fiscal year, then write the audit.

        The call is idempotent. A retry of the same action (same idempotency key)
        finds the cost center already set and changes nothing, so it writes no second
        audit entry.

        Returns:
            `True` after the assignment. The caller commits. `False` when the node is
            missing or the application already has this cost center. Nothing changed in
            that case.
        """
        node = await session.get(Budget, budget_id)
        if node is None:
            logger.warning("assignBudget: budget %s missing — skipped", budget_id)
            return False
        if await in_budget_vote_state(session, app):
            # The deciding Gremium of the running vote came from the current cost
            # center (`application.vote_gremium_id`). The manual route gives 409 here.
            logger.warning(
                "assignBudget: application %s is in a vote whose Gremium comes from "
                "the cost center — no change",
                app.id,
            )
            return False
        if app.budget_id == node.id:
            logger.info(
                "assignBudget: application %s already has budget %s — no change",
                app.id,
                node.id,
            )
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
        # Set the active fiscal year only when it is unambiguous. Otherwise leave it open.
        if len(active_ids) == 1:
            app.fiscal_year_id = active_ids[0]
        # A money mutation needs an audit trail. House rule, mirrors BudgetTreeService.
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
        """Walk the parent chain up to the top-level node (`parent_id IS NULL`)."""
        current = node
        seen: set[UUID] = set()
        while current.parent_id is not None and current.parent_id not in seen:
            seen.add(current.id)
            parent = await session.get(Budget, current.parent_id)
            if parent is None:
                break
            current = parent
        return current


async def _applicant_gremien(session: AsyncSession, sub: str | None) -> list[UUID]:
    """Return the Gremien where the applicant is a member now (as `applicantCommitteeIs`)."""
    return [UUID(g) for g in await committee_ids_for_sub(session, sub)]


def _parse_budget_uuid(label: str, ref: object) -> UUID | None:
    """Parse a budget reference into a UUID.

    An empty or invalid reference gives a log line and `None` (fail-closed). A value
    from a form field can be missing or garbage. The application then stays without a
    cost center. The budget guard is fail-closed itself.
    """
    if not ref:
        logger.warning("%s: empty budget reference — skipped", label)
        return None
    try:
        return UUID(str(ref))
    except ValueError:
        logger.warning("%s: invalid budget id %r — skipped", label, ref)
        return None
