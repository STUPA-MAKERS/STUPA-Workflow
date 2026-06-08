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

from app.modules.admin.models import ApplicationType
from app.modules.applications.models import Application, StatusEvent
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.modules.auth.principal import Principal
from app.modules.flow import context as flow_context
from app.modules.flow.dispatch import (
    ActionDispatcher,
    NullActionDispatcher,
    build_dispatched_actions,
)
from app.modules.flow.models import State, Transition
from app.modules.flow.routing import DecisionFacts, evaluate_decision
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

    async def _load_state(self, state_id: UUID) -> State | None:
        return (
            await self.session.execute(select(State).where(State.id == state_id))
        ).scalar_one_or_none()

    async def _decision_facts(self, app: Application) -> DecisionFacts:
        """Fakten für ``decision``-Routing: Betrag, Typ-Key, Antragsteller-Rollen.

        ``amount`` kommt direkt vom Antrag; ``type_key`` aus dem Antragstyp; die
        Antragsteller-Rollen werden (sofern beim Anlegen hinterlegt) aus
        ``data['_applicantRoles']`` gelesen (für intern angelegte Anträge, #24)."""
        type_key: str | None = None
        if app.type_id is not None:
            app_type = (
                await self.session.execute(
                    select(ApplicationType).where(ApplicationType.id == app.type_id)
                )
            ).scalar_one_or_none()
            if app_type is not None:
                type_key = app_type.key
        raw_roles = app.data.get("_applicantRoles") if isinstance(app.data, dict) else None
        roles = frozenset(raw_roles) if isinstance(raw_roles, list) else frozenset()
        return DecisionFacts(amount=app.amount, type_key=type_key, applicant_roles=roles)

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

    # --------------------------------------------------------- auto_advance
    async def auto_advance(
        self,
        application_id: UUID,
        principal: Principal,
        *,
        vote_result: str | None = None,
        deadline_passed: bool = False,
    ) -> TransitionResult | None:
        """Ersten **automatischen** Übergang feuern, dessen Guard erfüllt ist (#8).

        Vom Worker zyklisch aufgerufen (``manual=False``). Gibt das Ergebnis zurück,
        falls ein Übergang gefeuert wurde, sonst ``None``. Idempotent über das
        optimistische Locking in :meth:`fire` (konkurrierender Lauf → ``ConflictError``).
        """
        app = await self._load_app(application_id)
        if app.current_state_id is None:
            return None
        # Decision-State (#28): kein Guard-Scan, sondern Fakten-Routing — feuert
        # automatisch den Übergang zum aufgelösten Ziel.
        state = await self._load_state(app.current_state_id)
        if state is not None and state.kind == "decision":
            return await self.route_decision(application_id, principal, app=app, state=state)
        complete = await flow_context.fields_complete(self.session, app)
        ctx = flow_context.build_context(
            principal,
            fields_complete=complete,
            vote_result=vote_result,
            deadline_passed=deadline_passed,
            manual=False,
        )
        for t in await self._outgoing(app):
            if t.automatic and eval_guard(t.guard, ctx):
                return await self.fire(
                    application_id,
                    t.id,
                    principal,
                    note="auto",
                    vote_result=vote_result,
                    deadline_passed=deadline_passed,
                    manual=False,
                )
        return None

    # --------------------------------------------------------- decision routing
    async def route_decision(
        self,
        application_id: UUID,
        principal: Principal,
        *,
        app: Application | None = None,
        state: State | None = None,
    ) -> TransitionResult | None:
        """``decision``-State auflösen + den Übergang zum Ziel-State feuern (#28).

        Wertet ``config.rules`` gegen die Antrags-Fakten aus (erste passende Regel,
        sonst ``config.else``), sucht unter den ausgehenden Übergängen den, dessen
        Ziel-State-Key dem aufgelösten Key entspricht, und feuert ihn (``manual=False``).
        Gibt ``None``, wenn der aktuelle State kein ``decision`` ist."""
        if app is None:
            app = await self._load_app(application_id)
        if app.current_state_id is None:
            return None
        if state is None:
            state = await self._load_state(app.current_state_id)
        if state is None or state.kind != "decision":
            return None

        rules = state.config.get("rules") if isinstance(state.config, dict) else None
        fallback = state.config.get("else") if isinstance(state.config, dict) else None
        if not isinstance(rules, list) or not isinstance(fallback, str):
            raise ConflictError(
                f"decision state {state.key!r} is misconfigured", code="conflict"
            )
        facts = await self._decision_facts(app)
        target_key = evaluate_decision(rules, fallback, facts)

        for t in await self._outgoing(app):
            to_state = await self._load_state(t.to_state_id)
            if to_state is not None and to_state.key == target_key:
                return await self.fire(
                    application_id, t.id, principal, note="decision", manual=False
                )
        raise ConflictError(
            f"decision state {state.key!r} has no transition to {target_key!r}",
            code="conflict",
        )

    # ----------------------------------------------------------- branch firing
    async def fire_branch(
        self,
        application_id: UUID,
        branch: str,
        principal: Principal,
        *,
        note: str | None = None,
    ) -> TransitionResult:
        """Den Übergang des aktuellen vote/approval-States mit ``branch`` feuern (#28).

        ``branch`` ist ``pass``/``fail`` (vote) bzw. ``accept``/``reject`` (approval).
        404, wenn kein passender Branch-Übergang existiert."""
        app = await self._load_app(application_id)
        for t in await self._outgoing(app):
            if t.branch == branch:
                return await self.fire(
                    application_id, t.id, principal, note=note or branch, manual=False
                )
        raise NotFoundError(
            f"no '{branch}' transition from the application's current state"
        )

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

        # Audit-Trail (T-23, security.md §4): Statuswechsel append-only protokollieren,
        # **in derselben Transaktion** wie der State-Wechsel (atomar). Nur id-Referenzen
        # — keine PII/Notiz-Rohwerte (note kann Freitext sein → nur Vorhandensein).
        await AuditService(self.session).record(
            actor=principal.sub,
            action=AuditAction.STATUS_CHANGE,
            target_type="application",
            target_id=str(app.id),
            data={
                "fromStateId": str(from_state_id),
                "toStateId": str(to_state_id),
                "transitionId": str(transition.id),
                "statusEventId": str(status_event_id),
                "manual": manual,
                "hasNote": note is not None,
            },
        )
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
