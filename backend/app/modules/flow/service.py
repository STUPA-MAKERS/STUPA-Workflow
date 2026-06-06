"""Flow-/Status-Engine (T-14, flows §3/§9, data-model §5.2).

Zwei Operationen:

* :meth:`FlowService.available_transitions` — Übergänge ab dem aktuellen State, deren
  Guard für den Principal ``True`` ergibt (Guards serverseitig, T-05; RBAC fail-closed).
* :meth:`FlowService.fire` — einen Übergang **atomar** ausführen: ``from == current``
  prüfen, Guard auswerten (false → 409), in **einer** Transaktion State wechseln +
  ``status_event`` schreiben (optimistisches Locking über die ``from``-State-Bedingung
  → konkurrierende Transition → 409), danach Worker-Actions dispatchen.

Edit-Lock: ergibt sich aus ``state.edit_allowed`` des Ziel-States — T-12 ``patch``
prüft das und liefert 409 (``setEditLock`` wird daher inline behandelt, nicht dispatcht).
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application, StatusEvent
from app.modules.auth.principal import Principal
from app.modules.flow import context as flow_context
from app.modules.flow.dispatch import (
    ActionDispatcher,
    NullActionDispatcher,
    build_dispatched_actions,
)
from app.modules.flow.models import Transition
from app.modules.flow.schemas import TransitionOut, TransitionResult
from app.shared.errors import ConflictError, NotFoundError
from app.shared.guards import eval_guard


class FlowService:
    """An eine ``AsyncSession`` + einen :class:`ActionDispatcher` gebundene Engine."""

    def __init__(
        self, session: AsyncSession, dispatcher: ActionDispatcher | None = None
    ) -> None:
        self.session = session
        self.dispatcher: ActionDispatcher = dispatcher or NullActionDispatcher()

    # ----------------------------------------------------------------- helpers
    async def _load_app(self, application_id: UUID) -> Application:
        app = (
            await self.session.execute(
                select(Application).where(Application.id == application_id)
            )
        ).scalar_one_or_none()
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        return app

    async def _load_transition(self, transition_id: UUID) -> Transition:
        transition = (
            await self.session.execute(
                select(Transition).where(Transition.id == transition_id)
            )
        ).scalar_one_or_none()
        if transition is None:
            raise NotFoundError(f"transition {transition_id} not found")
        return transition

    async def _outgoing(self, app: Application) -> list[Transition]:
        return list(
            (
                await self.session.execute(
                    select(Transition)
                    .where(
                        Transition.flow_version_id == app.flow_version_id,
                        Transition.from_state_id == app.current_state_id,
                    )
                    .order_by(Transition.order)
                )
            )
            .scalars()
            .all()
        )

    # ------------------------------------------------------- available_transitions
    async def available_transitions(
        self,
        application_id: UUID,
        principal: Principal,
        *,
        vote_result: str | None = None,
        deadline_passed: bool = False,
    ) -> list[TransitionOut]:
        """Verfügbare Übergänge (Guards geprüft) für den aktuellen State + Principal."""
        app = await self._load_app(application_id)
        if app.current_state_id is None:
            return []
        complete = await flow_context.fields_complete(self.session, app)
        ctx = flow_context.build_context(
            principal,
            fields_complete=complete,
            vote_result=vote_result,
            deadline_passed=deadline_passed,
            manual=True,
        )
        transitions = await self._outgoing(app)
        return [
            TransitionOut(
                id=t.id,
                fromStateId=t.from_state_id,
                toStateId=t.to_state_id,
                label=t.label_i18n,
            )
            for t in transitions
            if eval_guard(t.guard, ctx)
        ]

    # ------------------------------------------------------------------- fire
    async def fire(
        self,
        application_id: UUID,
        transition_id: UUID,
        principal: Principal,
        *,
        note: str | None = None,
        vote_result: str | None = None,
        deadline_passed: bool = False,
        manual: bool = True,
    ) -> TransitionResult:
        """Übergang feuern. 404 (Antrag/Transition), 409 (State-Konflikt/Guard/Race)."""
        app = await self._load_app(application_id)
        transition = await self._load_transition(transition_id)

        if transition.flow_version_id != app.flow_version_id:
            raise NotFoundError("transition does not belong to this application's flow")
        if transition.from_state_id != app.current_state_id:
            raise ConflictError(
                "Transition is not available from the current state.",
                code="conflict",
            )

        complete = await flow_context.fields_complete(self.session, app)
        ctx = flow_context.build_context(
            principal,
            fields_complete=complete,
            vote_result=vote_result,
            deadline_passed=deadline_passed,
            manual=manual,
        )
        if not eval_guard(transition.guard, ctx):
            raise ConflictError("Transition guard not satisfied.", code="guard_failed")

        # --- Transaktion: optimistisches Locking über die `from`-State-Bedingung. --
        # Eine konkurrierende Transition hat `current_state_id` bereits verschoben →
        # rowcount 0 → 409 (flows §9.3 »konkurrierende Transition«).
        from_state_id = transition.from_state_id
        to_state_id = transition.to_state_id
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                update(Application)
                .where(
                    Application.id == app.id,
                    Application.current_state_id == from_state_id,
                )
                .values(current_state_id=to_state_id)
            ),
        )
        if result.rowcount != 1:
            await self.session.rollback()
            raise ConflictError(
                "Concurrent transition detected; application state changed.",
                code="conflict",
            )

        event = StatusEvent(
            application_id=app.id,
            from_state_id=from_state_id,
            to_state_id=to_state_id,
            transition_id=transition.id,
            actor=principal.sub,
            note=note,
        )
        self.session.add(event)
        await self.session.flush()
        status_event_id = event.id
        await self.session.commit()

        # --- Nach Commit: Worker-Actions dispatchen (idempotent, retrybar). --------
        dispatched = build_dispatched_actions(
            transition.actions,
            application_id=app.id,
            transition_id=transition.id,
            status_event_id=status_event_id,
        )
        await self.dispatcher.dispatch(dispatched)

        return TransitionResult(
            newStateId=to_state_id,
            statusEventId=status_event_id,
            dispatchedActions=[a.type for a in dispatched],
        )
