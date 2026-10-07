"""Global flow versioning: read the active graph, save new immutable versions.

Exactly one global flow exists for all application types.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from app.modules.admin.schemas import FlowVersionCreate, FlowVersionOut
from app.modules.admin.service.service_base import ConfigServiceBase
from app.modules.audit.actions import AuditAction
from app.modules.config_revision.service import (
    ENTITY_FLOW,
    GLOBAL_ID,
    ConfigRevisionService,
)
from app.modules.flow.models import FlowVersion, State, Transition
from app.shared.config_schemas import FlowGraph, FlowValidationError, validate_flow_graph
from app.shared.errors import ValidationProblem
from app.shared.guards import budget_ids_of_action


class FlowOps(ConfigServiceBase):
    """Read the active global flow graph and save new immutable versions."""

    async def get_active_global_flow(self) -> FlowGraph | None:
        """Read the graph of the active global flow.

        Returns:
            The graph of the active version. ``None`` when no global flow
            exists yet. The editor then starts with an empty graph.
        """
        version = await self.session.scalar(
            select(FlowVersion).where(FlowVersion.active.is_(True)).limit(1)
        )
        if version is None:
            return None
        states = (
            await self.session.scalars(select(State).where(State.flow_version_id == version.id))
        ).all()
        transitions = (
            await self.session.scalars(
                select(Transition)
                .where(Transition.flow_version_id == version.id)
                .order_by(Transition.order)
            )
        ).all()
        key_by_id = {s.id: s.key for s in states}
        return FlowGraph.model_validate(
            {
                "states": [
                    {
                        "key": s.key,
                        "label": s.label_i18n,
                        "color": s.color,
                        "editAllowed": s.edit_allowed,
                        "isInitial": s.is_initial,
                        "isTerminal": s.is_terminal,
                        "kind": s.kind,
                        "config": s.config or {},
                    }
                    for s in states
                ],
                "transitions": [
                    {
                        "from": key_by_id[t.from_state_id],
                        "to": key_by_id[t.to_state_id],
                        "label": t.label_i18n or None,
                        "color": t.color,
                        "guard": t.guard,
                        "actions": t.actions or [],
                        "order": t.order,
                        "automatic": t.automatic,
                        "branch": t.branch,
                        "requiresAction": t.requires_action,
                    }
                    for t in transitions
                ],
                "layout": version.editor_layout or None,
            }
        )

    async def create_global_flow_version(
        self,
        payload: FlowVersionCreate,
        actor: str,
        *,
        action: AuditAction = AuditAction.CONFIG_ACTIVATION,
        extra_data: dict | None = None,
    ) -> FlowVersionOut:
        """Save the global flow as a new, immutable version.

        Every save creates a new ``flow_version`` with fresh ``state`` and
        ``transition`` rows. Earlier versions stay untouched, together with
        their rows and their ``status_event`` references. A version is never
        deleted.

        Applications are not pinned to a version. The save moves ALL of them to
        the newest version by state KEY. A removed key falls back to the
        initial state. The graph must have exactly one initial state
        (``validate_flow_graph``).

        The save also writes a ``config_revision`` snapshot of the graph plus a
        linked audit entry. ``action`` and ``extra_data`` support the restore
        and revert path.

        Raises:
            ValidationProblem: The graph is invalid.
        """
        from app.modules.applications.models import Application

        try:
            validate_flow_graph(payload.graph)
        except FlowValidationError as exc:
            raise ValidationProblem(
                "Invalid flow graph.", errors=[{"field": "graph", "msg": str(exc)}]
            ) from exc
        await self._check_budget_refs(payload.graph)

        # The state KEY stays valid across versions, so remember it per application.
        # Also remember the deadline policy key of the old state (see
        # `_move_state_deadlines`).
        app_keys: dict[UUID, str] = {}
        old_policy_keys: dict[UUID, str | None] = {}
        for app_id, key, config in (
            await self.session.execute(
                select(Application.id, State.key, State.config).join(
                    State, State.id == Application.current_state_id
                )
            )
        ).all():
            app_keys[app_id] = key
            old_policy_keys[app_id] = _policy_key(config)

        # Deactivate the active version FIRST. The partial unique index
        # uq_flow_version_one_active_global, with its WHERE active clause, allows only
        # one active row. An insert of the new active row before the update collides.
        # session.execute flushes pending inserts, so this must run before the add.
        max_version = await self.session.scalar(
            select(FlowVersion.version).order_by(FlowVersion.version.desc()).limit(1)
        )
        await self.session.execute(
            update(FlowVersion).where(FlowVersion.active.is_(True)).values(active=False)
        )
        version = FlowVersion(
            version=(max_version or 0) + 1,
            active=True,
            editor_layout=payload.graph.layout or {},
        )
        self.session.add(version)
        await self.session.flush()

        id_by_key: dict[str, UUID] = {}
        state_by_key: dict[str, State] = {}
        initial_id: UUID | None = None
        initial_state: State | None = None
        for state in payload.graph.states:
            row = State(
                flow_version_id=version.id,
                key=state.key,
                label_i18n=state.label,
                color=state.color,
                edit_allowed=state.edit_allowed,
                is_initial=state.is_initial,
                is_terminal=state.is_terminal,
                kind=state.kind,
                config=state.config,
            )
            self.session.add(row)
            await self.session.flush()
            id_by_key[state.key] = row.id
            state_by_key[state.key] = row
            if state.is_initial:
                initial_id = row.id
                initial_state = row

        for order, trans in enumerate(payload.graph.transitions):
            self.session.add(
                Transition(
                    flow_version_id=version.id,
                    from_state_id=id_by_key[trans.from_],
                    to_state_id=id_by_key[trans.to],
                    label_i18n=trans.label or {},
                    color=trans.color,
                    guard=trans.guard,
                    actions=trans.actions,
                    order=trans.order if trans.order is not None else order,
                    automatic=trans.automatic,
                    branch=trans.branch,
                    requires_action=trans.requires_action,
                )
            )

        # The remap keeps `updated_at` unchanged. A flow edit does not change the
        # application. Without the explicit value, `onupdate=func.now()` sets the
        # activation time, and every `relative_changed` deadline moves later.
        for app_id, key in app_keys.items():
            await self.session.execute(
                update(Application)
                .where(Application.id == app_id)
                .values(
                    current_state_id=id_by_key.get(key, initial_id),
                    flow_version_id=version.id,
                    updated_at=Application.updated_at,
                )
            )
        await self.session.execute(
            update(Application)
            .where(Application.current_state_id.is_(None))
            .values(
                current_state_id=initial_id,
                flow_version_id=version.id,
                updated_at=Application.updated_at,
            )
        )
        await self._move_state_deadlines(app_keys, state_by_key, initial_state, old_policy_keys)
        await self._move_vote_gremium(list(state_by_key.values()))

        await ConfigRevisionService(self.session).record(
            entity_type=ENTITY_FLOW,
            entity_id=GLOBAL_ID,
            snapshot=payload.graph.model_dump(by_alias=True),
            actor=actor,
            action=action,
            extra_data={**(extra_data or {}), "global": True},
        )
        await self.session.commit()
        return FlowVersionOut(
            id=version.id,
            version=version.version,
            active=True,
        )

    async def _check_budget_refs(self, graph: FlowGraph) -> None:
        """Refuse a graph whose cost-center actions name an unknown cost center.

        `assignBudgetFromMap` names a cost center per field value, and
        `assignBudgetFromApplicantGremium` may name the root of its search. Both must
        exist, or the action could never assign anything.

        Raises:
            ValidationProblem: A referenced budget id is no UUID or does not exist (422).
        """
        from app.modules.budget.tree_models import Budget

        refs = {
            ref for t in graph.transitions for a in t.actions for ref in budget_ids_of_action(a)
        }
        if not refs:
            return
        ids: set[UUID] = set()
        bad: set[str] = set()
        for ref in refs:
            try:
                ids.add(UUID(ref))
            except ValueError:
                bad.add(ref)
        found = (
            set((await self.session.scalars(select(Budget.id).where(Budget.id.in_(ids)))).all())
            if ids
            else set()
        )
        bad |= {str(i) for i in ids - found}
        if bad:
            raise ValidationProblem(
                "Invalid flow graph.",
                errors=[
                    {"field": "graph", "msg": f"unknown cost center id {ref!r} in an action"}
                    for ref in sorted(bad)
                ],
            )

    async def _move_vote_gremium(self, states: list[State]) -> None:
        """Re-derive the vote Gremium snapshot of the moved applications.

        Every application now sits in a state of the new version. The snapshot
        follows that state:

        * a non-vote state clears it,
        * a vote state with a fixed `gremiumId` sets that Gremium (as the old code,
          which read the state config, did after an edit of the Gremium),
        * a vote state with `gremiumSource: "budget"` keeps a snapshot that exists.
          The vote runs on, and the snapshot stays what the application got on entry.
          An application without a snapshot gets the effective deciding Gremium of
          its cost center, or none. Such an application stays in the state; nobody
          but an admin can then vote on it, and a person moves it on by hand.

        The rows keep `updated_at`, like the state remap.
        """
        from app.modules.applications.models import Application
        from app.modules.flow.vote_gremium import gremium_from_budget, resolve_vote_gremium

        vote_states = [s for s in states if s.kind == "vote"]
        clear = update(Application).where(Application.vote_gremium_id.is_not(None))
        if vote_states:
            clear = clear.where(Application.current_state_id.not_in([s.id for s in vote_states]))
        await self.session.execute(
            clear.values(vote_gremium_id=None, updated_at=Application.updated_at)
        )
        for state in vote_states:
            if not gremium_from_budget(state):
                await self.session.execute(
                    update(Application)
                    .where(Application.current_state_id == state.id)
                    .values(
                        vote_gremium_id=await resolve_vote_gremium(self.session, state, None),
                        updated_at=Application.updated_at,
                    )
                )
                continue
            rows = (
                await self.session.execute(
                    select(Application.id, Application.budget_id).where(
                        Application.current_state_id == state.id,
                        Application.vote_gremium_id.is_(None),
                    )
                )
            ).all()
            for app_id, budget_id in rows:
                gremium = await resolve_vote_gremium(self.session, state, budget_id)
                if gremium is not None:
                    await self.session.execute(
                        update(Application)
                        .where(Application.id == app_id)
                        .values(vote_gremium_id=gremium, updated_at=Application.updated_at)
                    )

    async def _move_state_deadlines(
        self,
        app_keys: dict[UUID, str],
        state_by_key: dict[str, State],
        initial_state: State | None,
        old_policy_keys: dict[UUID, str | None],
    ) -> None:
        """Re-create the flow deadlines of the moved applications on the new version.

        An open deadline points at a transition of the old version. The cron cannot
        fire it any more, because `fire` refuses a transition of another flow version.
        So every moved application gets the deadline of its new state, with the
        target transition of the new version (`schedule_state_deadline`).

        When the new state keeps the `deadlinePolicyKey` of the old state and a
        deadline exists, the old due time stays. The policy is not resolved again. A
        `recurring` policy resolves to the next date after now. A second resolve thus
        moves an expired deadline to a later date, or removes it when all dates are
        past, and `deadlinePassed` becomes false again. Only a changed policy key, or
        an application without a deadline, gets a new due time.

        The reminder and consumed markers carry over when the due time stays the
        same. The applicant then gets no second reminder, and an expired deadline
        that already fired or failed does not fire again because of a flow edit.
        Everything runs in the transaction of the caller.
        """
        from app.modules.applications.models import Application
        from app.modules.deadlines.models import Deadline
        from app.modules.flow.service import FlowService

        if not app_keys:
            return
        app_ids = list(app_keys)
        old_marks: dict[UUID, tuple[datetime, datetime | None, Any]] = {
            d.application_id: (d.due_at, d.reminded_at, d.action_on_pass)
            for d in (
                await self.session.scalars(
                    select(Deadline).where(
                        Deadline.application_id.in_(app_ids),
                        Deadline.kind == "flow_deadline",
                    )
                )
            ).all()
            if d.application_id is not None
        }
        apps = (
            await self.session.scalars(
                select(Application)
                .where(Application.id.in_(app_ids))
                .execution_options(populate_existing=True)
            )
        ).all()
        flow = FlowService(self.session)
        now = datetime.now(UTC)
        for app in apps:
            state = state_by_key.get(app_keys[app.id], initial_state)
            if state is None:
                continue
            mark = old_marks.get(app.id)
            new_key = _policy_key(state.config)
            same_policy = new_key is not None and old_policy_keys.get(app.id) == new_key
            deadline = await flow.schedule_state_deadline(
                app,
                state,
                commit=False,
                due_at=mark[0] if mark is not None and same_policy else None,
            )
            if deadline is None or mark is None or deadline.due_at != mark[0]:
                continue
            due_at, reminded_at, action_on_pass = mark
            deadline.reminded_at = reminded_at
            if action_on_pass is None and due_at <= now:
                deadline.action_on_pass = None


def _policy_key(config: object) -> str | None:
    """Return the `deadlinePolicyKey` of a state config, or `None`."""
    if not isinstance(config, dict):
        return None
    key = config.get("deadlinePolicyKey")
    return key if isinstance(key, str) and key else None
