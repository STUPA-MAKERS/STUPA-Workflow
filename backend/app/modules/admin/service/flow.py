"""Global flow versioning: read the active graph, save new immutable versions.

Exactly one global flow exists for all application types.
"""

from __future__ import annotations

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
            await self.session.scalars(
                select(State).where(State.flow_version_id == version.id)
            )
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

        # The state KEY stays valid across versions, so remember it per application.
        app_keys = {
            app_id: key
            for app_id, key in (
                await self.session.execute(
                    select(Application.id, State.key).join(
                        State, State.id == Application.current_state_id
                    )
                )
            ).all()
        }

        # Deactivate the active version FIRST. The partial unique index
        # uq_flow_version_one_active_global, with its WHERE active clause, allows only
        # one active row. An insert of the new active row before the update collides.
        # session.execute flushes pending inserts, so this must run before the add.
        max_version = await self.session.scalar(
            select(FlowVersion.version).order_by(FlowVersion.version.desc()).limit(1)
        )
        await self.session.execute(
            update(FlowVersion)
            .where(FlowVersion.active.is_(True))
            .values(active=False)
        )
        version = FlowVersion(
            version=(max_version or 0) + 1,
            active=True,
            editor_layout=payload.graph.layout or {},
        )
        self.session.add(version)
        await self.session.flush()

        id_by_key: dict[str, UUID] = {}
        initial_id: UUID | None = None
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
            if state.is_initial:
                initial_id = row.id

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

        for app_id, key in app_keys.items():
            await self.session.execute(
                update(Application)
                .where(Application.id == app_id)
                .values(
                    current_state_id=id_by_key.get(key, initial_id),
                    flow_version_id=version.id,
                )
            )
        await self.session.execute(
            update(Application)
            .where(Application.current_state_id.is_(None))
            .values(current_state_id=initial_id, flow_version_id=version.id)
        )

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
