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

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import ApplicationType, GremiumMembership, GremiumRole
from app.modules.applications.models import Application, StatusEvent
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.flow import context as flow_context
from app.modules.flow.dispatch import (
    ActionDispatcher,
    NullActionDispatcher,
    build_dispatched_actions,
)
from app.modules.deadlines.models import Deadline
from app.modules.deadlines.service import (
    DeadlinePolicyService,
    DeadlineService,
    resolve_due_at,
)
from app.modules.flow.models import State, Transition
from app.modules.flow.routing import DecisionFacts, evaluate_decision
from app.modules.flow.schemas import TransitionOut, TransitionResult
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError
from app.shared.guards import eval_guard


def _guard_fires_on_deadline(guard: Any) -> bool:
    """``True`` wenn der Guard (rekursiv durch ``and``/``or``/``not``) den Operator
    ``deadlinePassed`` mit Wahrheitswert ``true`` enthält — also der Übergang, den die
    Frist beim Ablauf feuern soll (flows §9.4)."""
    if not isinstance(guard, dict):
        return False
    for op, value in guard.items():
        if op == "deadlinePassed":
            return bool(value)
        if op in ("and", "or") and isinstance(value, list):
            if any(_guard_fires_on_deadline(g) for g in value):
                return True
        elif op == "not" and _guard_fires_on_deadline(value):
            return True
    return False


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

    # ------------------------------------------------------- deadline scheduling
    async def schedule_state_deadline(self, app: Application, state: State) -> None:
        """Beim Betreten eines States dessen benannte Frist-Policy materialisieren (#13).

        Trägt der ``state.config`` einen ``deadlinePolicyKey``, wird die Policy aufgelöst
        (``absolute`` → Datum; ``relative_submitted`` → ``created_at + X``;
        ``relative_changed`` → ``updated_at + X``) und eine :class:`Deadline` mit
        ``action_on_pass`` auf den ``deadlinePassed``-Übergang dieses States angelegt.
        Der bestehende T-44-Cron feuert sie bei Ablauf. Eventuelle frühere, noch nicht
        gefeuerte Flow-Fristen des Antrags werden zuvor entfernt (kein Stapeln bei
        erneutem State-Wechsel)."""
        cfg = state.config if isinstance(state.config, dict) else {}
        key = cfg.get("deadlinePolicyKey")
        if not isinstance(key, str) or not key:
            return
        policy = await DeadlinePolicyService(self.session).get_by_key(key)
        if policy is None:
            return
        due_at = resolve_due_at(
            policy, submitted_at=app.created_at, changed_at=app.updated_at
        )
        if due_at is None:
            return
        # Ziel-Übergang = der vom State ausgehende Übergang mit Guard ``deadlinePassed``.
        transitions = (
            await self.session.execute(
                select(Transition).where(
                    Transition.flow_version_id == app.flow_version_id,
                    Transition.from_state_id == state.id,
                )
            )
        ).scalars().all()
        target = next(
            (t for t in transitions if _guard_fires_on_deadline(t.guard)), None
        )
        if target is None:
            return
        # Alte, noch nicht gefeuerte Flow-Fristen des Antrags entfernen (Idempotenz).
        await self.session.execute(
            Deadline.__table__.delete().where(
                Deadline.application_id == app.id,
                Deadline.kind == "flow_deadline",
                Deadline.action_on_pass.isnot(None),
            )
        )
        await DeadlineService(self.session).create(
            kind="flow_deadline",
            due_at=due_at,
            application_id=app.id,
            action_on_pass={"transitionId": str(target.id)},
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
    async def branch_transition(
        self, application_id: UUID, branch: str
    ) -> Transition | None:
        """Ausgehenden Übergang des aktuellen States mit ``branch`` finden (#28).

        ``branch`` ist ``pass``/``fail`` (vote) bzw. ``accept``/``reject`` (approval);
        ``None``, wenn der aktuelle State keinen solchen Branch-Ausgang hat."""
        app = await self._load_app(application_id)
        for t in await self._outgoing(app):
            if t.branch == branch:
                return t
        return None

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
        t = await self.branch_transition(application_id, branch)
        if t is None:
            raise NotFoundError(
                f"no '{branch}' transition from the application's current state"
            )
        return await self.fire(
            application_id, t.id, principal, note=note or branch, manual=False
        )

    # --------------------------------------------------------- approval states
    async def _has_gremium_role(
        self, sub: str, role_key: str, gremium_id: UUID
    ) -> bool:
        """``True`` wenn ``sub`` aktuell die Gremium-Rolle ``role_key`` im Gremium hält
        (#28/#62). Wertet das tz-aware Amtszeit-Fenster der Mitgliedschaft aus —
        gegen die **gremium-eigenen** Rollen (``gremium_membership``/``gremium_role``)."""
        now = datetime.now(UTC)
        row = (
            await self.session.execute(
                select(GremiumMembership.id)
                .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
                .join(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
                .where(
                    PrincipalRow.sub == sub,
                    GremiumRole.key == role_key,
                    GremiumMembership.gremium_id == gremium_id,
                    (GremiumMembership.valid_from.is_(None))
                    | (GremiumMembership.valid_from <= now),
                    (GremiumMembership.valid_until.is_(None))
                    | (GremiumMembership.valid_until > now),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return row is not None

    async def submit_approval(
        self, application_id: UUID, decision: str, principal: Principal
    ) -> TransitionResult:
        """Approval-State entscheiden: ``accept``/``reject`` feuert den Branch (#28).

        Der aktuelle State muss ``kind == 'approval'`` sein; nur ein Principal mit der
        konfigurierten Rolle (``config.roleKey``) im Gremium (``config.gremiumId``) —
        oder ein Admin (#15) — darf entscheiden (403 sonst)."""
        if decision not in ("accept", "reject"):
            raise ConflictError(f"invalid approval decision {decision!r}", code="conflict")
        app = await self._load_app(application_id)
        if app.current_state_id is None:
            raise ConflictError("application has no current state", code="conflict")
        state = await self._load_state(app.current_state_id)
        if state is None or state.kind != "approval":
            raise ConflictError(
                "current state is not an approval state", code="conflict"
            )
        cfg = state.config if isinstance(state.config, dict) else {}
        role_key = cfg.get("roleKey")
        gremium_id = cfg.get("gremiumId")
        if not isinstance(role_key, str):
            raise ConflictError(
                f"approval state {state.key!r} is misconfigured", code="conflict"
            )
        # Globale Rolle (kein gremiumId) → Principal-Rolle; sonst Gremium-Rolle (#28).
        if isinstance(gremium_id, str) and gremium_id:
            authorized = "admin" in principal.roles or await self._has_gremium_role(
                principal.sub, role_key, UUID(gremium_id)
            )
            scope = "in the configured gremium"
        else:
            authorized = role_key in principal.roles or "admin" in principal.roles
            scope = "globally"
        if not authorized:
            raise ForbiddenError(f"requires role {role_key!r} {scope}")
        return await self.fire_branch(
            application_id, decision, principal, note=f"approval:{decision}"
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

        # Frist des neuen States materialisieren (#13): trägt er eine benannte
        # Deadline-Policy, legt das eine fällige Frist an, die der T-44-Cron feuert.
        to_state = await self._load_state(to_state_id)
        if to_state is not None:
            await self.session.refresh(app)
            await self.schedule_state_deadline(app, to_state)

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
