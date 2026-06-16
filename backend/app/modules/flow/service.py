"""Flow-/Status-Engine (T-14, flows §3/§9, data-model §5.2).

Operationen:

* :meth:`FlowService.available_transitions` — manuelle Übergänge ab dem aktuellen
  State, deren Guard für den Akteur ``True`` ergibt (Guards serverseitig, T-05;
  Akteur-Gates fail-closed). Basis der Trigger-UI in der Antrags-Detailansicht.
* :meth:`FlowService.fire` — einen Übergang **atomar** ausführen.
* :meth:`FlowService.auto_advance` — den ersten **automatischen** Übergang feuern,
  dessen Guard erfüllt ist (vom Worker/Cron zyklisch, ``manual=False``).
* :meth:`FlowService.fire_branch` — den ``pass``/``fail``-Ausgang eines ``vote``-
  States feuern (vom Voting-Modul beim Schließen).

Edit-Lock: ergibt sich aus ``state.edit_allowed`` des Ziel-States — T-12 ``patch``
prüft das und liefert 409 (inline behandelt, nicht dispatcht).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application, StatusEvent
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.modules.auth.principal import Principal
from app.modules.deadlines.models import Deadline
from app.modules.deadlines.service import (
    DeadlinePolicyService,
    DeadlineService,
    resolve_due_at,
)
from app.modules.flow import context as flow_context
from app.modules.flow.dispatch import (
    ActionDispatcher,
    NullActionDispatcher,
    build_dispatched_actions,
    build_implicit_notifications,
)
from app.modules.flow.models import State, Transition
from app.modules.flow.schemas import TransitionOut, TransitionResult
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError
from app.shared.guards import GuardContext, eval_guard, guard_requires_applicant


def _guard_fires_on_deadline(guard: Any, *, negated: bool = False) -> bool:
    """``True`` wenn der Guard (rekursiv durch ``and``/``or``/``not``) bei
    **abgelaufener** Frist feuern soll (flows §9.4) — d. h. ``deadlinePassed`` unter
    Berücksichtigung der Negations-Polarität ``true`` verlangt:
    ``{deadlinePassed: true}`` und ``not(deadlinePassed: false)`` zählen,
    ``not(deadlinePassed: true)`` nicht."""
    if not isinstance(guard, dict):
        return False
    for op, value in guard.items():
        if op == "deadlinePassed":
            if bool(value) != negated:
                return True
        elif op in ("and", "or") and isinstance(value, list):
            if any(_guard_fires_on_deadline(g, negated=negated) for g in value):
                return True
        elif op == "not":
            children = value if isinstance(value, list) else [value]
            if any(_guard_fires_on_deadline(g, negated=not negated) for g in children):
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
        Der bestehende T-44-Cron feuert sie bei Ablauf. Gibt es keinen solchen Übergang,
        wird die Frist als reiner Marker (``action_on_pass=NULL``) angelegt — Basis für
        ``deadlinePassed`` auf **manuellen** Übergängen (:meth:`_deadline_passed`).

        Flow-Fristen des verlassenen States (auch konsumierte) werden **immer** zuerst
        entfernt — kein Stapeln, keine stale Fristen nach Wechsel in einen State ohne
        Policy."""
        await self.session.execute(
            delete(Deadline).where(
                Deadline.application_id == app.id,
                Deadline.kind == "flow_deadline",
            )
        )
        cfg = state.config if isinstance(state.config, dict) else {}
        key = cfg.get("deadlinePolicyKey")
        if not isinstance(key, str) or not key:
            await self.session.commit()
            return
        policy = await DeadlinePolicyService(self.session).get_by_key(key)
        if policy is None:
            await self.session.commit()
            return
        due_at = resolve_due_at(
            policy, submitted_at=app.created_at, changed_at=app.updated_at
        )
        if due_at is None:
            await self.session.commit()
            return
        # Ziel-Übergang = der vom State ausgehende Übergang, der bei abgelaufener Frist
        # feuern soll (``deadlinePassed``-Polarität inkl. Negation); bei mehreren
        # Kandidaten deterministisch der mit der kleinsten ``order``.
        transitions = (
            await self.session.execute(
                select(Transition)
                .where(
                    Transition.flow_version_id == app.flow_version_id,
                    Transition.from_state_id == state.id,
                )
                .order_by(Transition.order)
            )
        ).scalars().all()
        candidates = [t for t in transitions if _guard_fires_on_deadline(t.guard)]
        target = self._pick_deadline_transition(candidates)
        await DeadlineService(self.session).create(
            kind="flow_deadline",
            due_at=due_at,
            application_id=app.id,
            action_on_pass=(
                {"transitionId": str(target.id)} if target is not None else None
            ),
        )

    # Minimal-Kontext: nur die Frist gilt als erfüllt, sonst nichts (keine Rollen,
    # kein Budget-Fit, keine Feldwerte). Ein Kandidat, dessen vollständiger Guard
    # SCHON hier ``True`` ergibt, verlangt nichts außer der abgelaufenen Frist und
    # feuert daher bei Ablauf garantiert — I/O-frei zur Schedule-Zeit auswertbar.
    _DEADLINE_ONLY_CTX = GuardContext(manual=False, deadline_passed=True)

    @classmethod
    def _pick_deadline_transition(
        cls, candidates: list[Transition]
    ) -> Transition | None:
        """Aus den ``deadlinePassed``-Kandidaten (nach ``order``) den ersten wählen,
        dessen **vollständiger** Guard allein durch die abgelaufene Frist erfüllt ist
        (#deadline-guard).

        Der alte Code pinnte stur den ersten ``deadlinePassed``-Übergang — hatte der
        ein weiteres UND-verknüpftes Prädikat, feuerte er bei Ablauf nicht, der Cron
        verbrauchte die Frist trotzdem (``ConflictError`` → ``action_on_pass=NULL``)
        und der Antrag blieb fristlos hängen, obwohl ein Geschwister-Übergang allein
        auf die Frist hörte. Darum jetzt: den ersten Kandidaten nehmen, dessen Guard
        unter :data:`_DEADLINE_ONLY_CTX` (nur ``deadline_passed=True``, sonst leer)
        hält — der feuert garantiert. Hält **keiner** ohne Zusatzbedingung, den ersten
        als reinen Marker pinnen (Rückwärtsverhalten — Frist bleibt sichtbar)."""
        if not candidates:
            return None
        for t in candidates:
            if eval_guard(t.guard, cls._DEADLINE_ONLY_CTX):
                return t
        return candidates[0]

    async def _deadline_passed(self, app: Application) -> bool:
        """Echtes ``deadline_passed`` des aktuellen States aus der DB ableiten.

        ``True``, wenn eine (ggf. schon konsumierte) Flow-Frist des Antrags abgelaufen
        ist. Fristen gehören immer zum aktuellen State — beim State-Wechsel räumt
        :meth:`schedule_state_deadline` alle alten ab. Für manuelle Pfade (Router),
        damit ``deadlinePassed``-Guards nicht nur für den Worker funktionieren."""
        row = await self.session.scalar(
            select(Deadline.id)
            .where(
                Deadline.application_id == app.id,
                Deadline.kind == "flow_deadline",
                Deadline.due_at <= datetime.now(UTC),
            )
            .limit(1)
        )
        return row is not None

    # ------------------------------------------------------- available_transitions
    async def available_transitions(
        self,
        application_id: UUID,
        principal: Principal,
        *,
        deadline_passed: bool | None = None,
    ) -> list[TransitionOut]:
        """Verfügbare **manuelle** Übergänge (Guards geprüft) für den Akteur.

        Automatische Übergänge werden ausgeblendet — sie feuert der Worker, nicht der
        Nutzer. **Ergebnis-Branches** (``branch`` gesetzt, z. B. die pass/fail-Ausgänge
        eines vote/approval-States) ebenfalls: sie entscheidet allein die Abstimmung
        (``close_vote``), nie eine manuelle Aktion (#vote-branch). Akteur-Gates im Guard
        verfeinern die Sichtbarkeit der übrigen Übergänge.
        ``deadline_passed=None`` ⇒ aus der DB ableiten."""
        app = await self._load_app(application_id)
        if app.current_state_id is None:
            return []
        if deadline_passed is None:
            deadline_passed = await self._deadline_passed(app)
        ctx = await flow_context.build_context(
            self.session, app, principal, manual=True, deadline_passed=deadline_passed
        )
        return [
            TransitionOut(
                id=t.id,
                fromStateId=t.from_state_id,
                toStateId=t.to_state_id,
                label=t.label_i18n,
                color=t.color,
                requiresAction=t.requires_action,
            )
            for t in await self._outgoing(app)
            if not t.automatic and not t.branch and eval_guard(t.guard, ctx)
        ]

    # ------------------------------------------------- applicant transitions
    _APPLICANT = Principal(sub="applicant", roles=[], permissions=set())

    async def available_applicant_transitions(
        self, application_id: UUID
    ) -> list[TransitionOut]:
        """Übergänge, die der **Magic-Link-Antragsteller** feuern darf: manuell,
        Guard erfüllt im Applicant-Kontext **und** explizit per ``actorIsApplicant``
        freigegeben (sonst nichts — kein impliziter Antragsteller-Zugriff)."""
        app = await self._load_app(application_id)
        if app.current_state_id is None:
            return []
        ctx = await flow_context.build_context(
            self.session, app, self._APPLICANT, manual=True, as_applicant=True
        )
        return [
            TransitionOut(
                id=t.id,
                fromStateId=t.from_state_id,
                toStateId=t.to_state_id,
                label=t.label_i18n,
                color=t.color,
                requiresAction=t.requires_action,
            )
            for t in await self._outgoing(app)
            if not t.automatic
            and not t.branch
            and guard_requires_applicant(t.guard)
            and eval_guard(t.guard, ctx)
        ]

    async def fire_as_applicant(
        self, application_id: UUID, transition_id: UUID, *, note: str | None = None
    ) -> TransitionResult:
        """Übergang als Antragsteller feuern — nur ``actorIsApplicant``-freigegebene,
        manuelle Übergänge (403 sonst). Umgeht damit gezielt das ``application.manage``-
        Gate, aber **nur** für vom Admin bewusst geöffnete Übergänge."""
        transition = await self._load_transition(transition_id)
        if transition.automatic or not guard_requires_applicant(transition.guard):
            raise ForbiddenError("transition is not open to the applicant")
        return await self.fire(
            application_id, transition_id, self._APPLICANT, note=note, as_applicant=True
        )

    # --------------------------------------------------------- auto_advance
    async def auto_advance(
        self,
        application_id: UUID,
        principal: Principal,
        *,
        deadline_passed: bool | None = None,
    ) -> TransitionResult | None:
        """Ersten **automatischen** Übergang feuern, dessen Guard erfüllt ist (#8).

        Vom Worker/Cron zyklisch aufgerufen (``manual=False``). Gibt das Ergebnis
        zurück, falls ein Übergang gefeuert wurde, sonst ``None``. Idempotent über das
        optimistische Locking in :meth:`fire`. ``deadline_passed=None`` ⇒ aus der DB
        ableiten."""
        app = await self._load_app(application_id)
        if app.current_state_id is None:
            return None
        # Fail-closed (#vote-bypass): einen vote-State entscheidet nur die Abstimmung
        # (oder ein manueller Abbruch) — automatische Ausgänge werden hier NIE gefeuert,
        # auch wenn ein (Alt-)Flow sie noch enthält; der Graph-Validator lehnt sie beim
        # Speichern inzwischen ab. Sonst wäre der Antrag »sofort angenommen«, ohne dass
        # je abgestimmt wurde.
        state = await self._load_state(app.current_state_id)
        if state is not None and state.kind == "vote":
            return None
        if deadline_passed is None:
            deadline_passed = await self._deadline_passed(app)
        ctx = await flow_context.build_context(
            self.session, app, principal, manual=False, deadline_passed=deadline_passed
        )
        for t in await self._outgoing(app):
            if t.automatic and eval_guard(t.guard, ctx):
                return await self.fire(
                    application_id,
                    t.id,
                    principal,
                    note="auto",
                    deadline_passed=deadline_passed,
                    manual=False,
                )
        return None

    # ----------------------------------------------------------- branch firing
    async def branch_transition(
        self, application_id: UUID, branch: str
    ) -> Transition | None:
        """Ausgehenden Übergang des aktuellen States mit ``branch`` finden (#28).

        ``branch`` ist ``pass``/``fail`` eines ``vote``-States; ``None``, wenn der
        aktuelle State keinen solchen Branch-Ausgang hat."""
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
        """Den ``pass``/``fail``-Übergang des aktuellen ``vote``-States feuern (#28).

        404, wenn kein passender Branch-Übergang existiert."""
        t = await self.branch_transition(application_id, branch)
        if t is None:
            raise NotFoundError(
                f"no '{branch}' transition from the application's current state"
            )
        return await self.fire(
            application_id, t.id, principal, note=note or branch, manual=False
        )

    async def _cancel_open_votes(self, application_id: UUID) -> None:
        """Offene Abstimmungen des Antrags stornieren (``open → cancelled``)."""
        # Lokaler Import: ``voting.service`` importiert den FlowService — ein
        # Modul-Level-Import hier wäre ein Zyklus.
        from app.modules.voting.models import Vote

        await self.session.execute(
            update(Vote)
            .where(Vote.application_id == application_id, Vote.status == "open")
            .values(status="cancelled")
        )

    # ------------------------------------------------------------------- fire
    async def fire(
        self,
        application_id: UUID,
        transition_id: UUID,
        principal: Principal,
        *,
        note: str | None = None,
        deadline_passed: bool | None = None,
        manual: bool = True,
        as_applicant: bool = False,
    ) -> TransitionResult:
        """Übergang feuern. 404 (Antrag/Transition), 409 (State-Konflikt/Guard/Race).

        ``deadline_passed=None`` ⇒ aus der DB ableiten (manuelle Pfade); der
        Deadline-Worker übergibt explizit ``True``."""
        app = await self._load_app(application_id)
        transition = await self._load_transition(transition_id)

        if transition.flow_version_id != app.flow_version_id:
            raise NotFoundError("transition does not belong to this application's flow")
        if transition.from_state_id != app.current_state_id:
            raise ConflictError(
                "Transition is not available from the current state.",
                code="conflict",
            )
        # Branch-Übergänge (pass/fail eines vote-States) feuert ausschließlich das
        # Vote-Ergebnis (fire_branch, manual=False) — nie ein Nutzer direkt, sonst
        # ließe sich der Vote-Ausgang an der Abstimmung vorbei setzen.
        if manual and transition.branch is not None:
            raise ConflictError(
                "Branch transitions are fired by the vote outcome, not manually.",
                code="conflict",
            )

        if deadline_passed is None:
            deadline_passed = await self._deadline_passed(app)
        ctx = await flow_context.build_context(
            self.session, app, principal, manual=manual,
            deadline_passed=deadline_passed, as_applicant=as_applicant,
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

        # Nicht-Branch-Ausgang (manuell »Wahl abbrechen« oder automatischer
        # Deadline-Exit aus einem vote-State, #abort-vote): offene Abstimmungen des
        # Antrags werden in derselben Transaktion storniert — sonst bliebe der Vote
        # offen und sein close() fände im neuen State keinen Branch mehr (409, für
        # immer offen). Vote-Ergebnis-Branches stornieren nichts: close() hat den
        # Vote dort bereits geschlossen.
        if transition.branch is None:
            await self._cancel_open_votes(app.id)

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
        # Implizite Auto-Mails (#4-3): Status-Update an den Antragsteller +
        # Task-Mail an Handlungsberechtigte des neuen States.
        dispatched += build_implicit_notifications(
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
