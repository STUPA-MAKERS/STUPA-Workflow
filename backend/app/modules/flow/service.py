"""Flow/status engine.

Operations:

* :meth:`FlowService.available_transitions` — manual transitions from the current
  state whose guard evaluates ``True`` for the actor (guards are server-side; actor
  gates fail-closed). Backs the trigger UI in the application detail view.
* :meth:`FlowService.fire` — execute a transition atomically.
* :meth:`FlowService.auto_advance` — fire the first automatic transition whose guard
  holds (cyclically by the worker/cron, ``manual=False``).
* :meth:`FlowService.fire_branch` — fire the ``pass``/``fail`` exit of a ``vote``
  state (from the voting module on close).

Edit lock: derived from the target state's ``state.edit_allowed`` — the ``patch`` path
checks it and returns 409 (handled inline, not dispatched).
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application, StatusEvent
from app.modules.applications.schemas import StateOut
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.modules.auth.principal import Principal
from app.modules.deadlines.models import Deadline
from app.modules.deadlines.service import (
    DeadlinePolicyService,
    DeadlineService,
    flow_deadline_passed,
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
    """Whether the guard (recursively through ``and``/``or``/``not``) should fire on an
    expired deadline — i.e. requires ``deadlinePassed`` true under negation polarity:
    ``{deadlinePassed: true}`` and ``not(deadlinePassed: false)`` count,
    ``not(deadlinePassed: true)`` does not."""
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
    """Engine bound to an ``AsyncSession`` + an :class:`ActionDispatcher`."""

    def __init__(
        self, session: AsyncSession, dispatcher: ActionDispatcher | None = None
    ) -> None:
        self.session = session
        self.dispatcher: ActionDispatcher = dispatcher or NullActionDispatcher()

    # --- helpers ---
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

    # --- deadline scheduling ---
    async def schedule_state_deadline(self, app: Application, state: State) -> None:
        """On entering a state, materialize its named deadline policy.

        If ``state.config`` carries a ``deadlinePolicyKey``, the policy is resolved
        (``absolute`` → date; ``relative_submitted`` → ``created_at + X``;
        ``relative_changed`` → ``updated_at + X``) and a :class:`Deadline` with
        ``action_on_pass`` pointing at this state's ``deadlinePassed`` transition is
        created; the cron fires it on expiry. Without such a transition the deadline is a
        pure marker (``action_on_pass=NULL``) — the basis for ``deadlinePassed`` on
        manual transitions (:meth:`_deadline_passed`).

        Flow deadlines of the left state (even consumed ones) are always removed first —
        no stacking, no stale deadlines after moving into a state without a policy."""
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
        # Target = the state's outgoing transition that should fire on an expired
        # deadline (``deadlinePassed`` polarity incl. negation); with several candidates
        # deterministically the one with the smallest ``order``.
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

    # Minimal context: only the deadline counts as satisfied, nothing else (no roles,
    # no budget fit, no field values). A candidate whose full guard is already ``True``
    # here needs nothing beyond the expired deadline and so fires on expiry for sure —
    # evaluable I/O-free at schedule time.
    _DEADLINE_ONLY_CTX = GuardContext(manual=False, deadline_passed=True)

    @classmethod
    def _pick_deadline_transition(
        cls, candidates: list[Transition]
    ) -> Transition | None:
        """From the ``deadlinePassed`` candidates (by ``order``) pick the first whose
        full guard is satisfied by the expired deadline alone.

        Picking the first candidate whose guard holds under :data:`_DEADLINE_ONLY_CTX`
        (only ``deadline_passed=True``, otherwise empty) ensures it fires on expiry: a
        candidate with an extra AND predicate would not fire, yet the cron would consume
        the deadline (``ConflictError`` → ``action_on_pass=NULL``) and the application
        would hang deadline-less. If none holds without an extra condition, pin the first
        as a pure marker (deadline stays visible)."""
        if not candidates:
            return None
        for t in candidates:
            if eval_guard(t.guard, cls._DEADLINE_ONLY_CTX):
                return t
        return candidates[0]

    async def _deadline_passed(self, app: Application) -> bool:
        """Derive the real ``deadline_passed`` of the current state from the DB.

        Delegates to :func:`flow_deadline_passed` (deadlines service) — the same
        derivation the task-mail recipient resolution uses."""
        return await flow_deadline_passed(self.session, app.id)

    # --- available_transitions ---
    async def available_transitions(
        self,
        application_id: UUID,
        principal: Principal,
        *,
        deadline_passed: bool | None = None,
    ) -> list[TransitionOut]:
        """Available manual transitions (guards checked) for the actor.

        Automatic transitions are hidden — the worker fires them, not the user. Result
        branches (``branch`` set, e.g. the pass/fail exits of a vote/approval state) too:
        only the vote (``close_vote``) decides them, never a manual action. Actor gates
        in the guard refine the visibility of the remaining transitions.
        ``deadline_passed=None`` ⇒ derive from the DB."""
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

    # --- applicant transitions ---
    _APPLICANT = Principal(sub="applicant", roles=[], permissions=set())

    async def available_applicant_transitions(
        self, application_id: UUID
    ) -> list[TransitionOut]:
        """Transitions the magic-link applicant may fire: manual, guard satisfied in the
        applicant context, and explicitly opened via ``actorIsApplicant`` (otherwise
        none — no implicit applicant access)."""
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
        """Fire a transition as the applicant — only ``actorIsApplicant``-opened, manual
        transitions (403 otherwise). Deliberately bypasses the ``application.manage``
        gate, but only for transitions the admin intentionally opened."""
        transition = await self._load_transition(transition_id)
        if transition.automatic or not guard_requires_applicant(transition.guard):
            raise ForbiddenError("transition is not open to the applicant")
        return await self.fire(
            application_id, transition_id, self._APPLICANT, note=note, as_applicant=True
        )

    # --- auto_advance ---
    async def auto_advance(
        self,
        application_id: UUID,
        principal: Principal,
        *,
        deadline_passed: bool | None = None,
    ) -> TransitionResult | None:
        """Fire the first automatic transition whose guard holds.

        Called cyclically by the worker/cron (``manual=False``). Returns the result if a
        transition fired, else ``None``. Idempotent via the optimistic locking in
        :meth:`fire`. ``deadline_passed=None`` ⇒ derive from the DB."""
        app = await self._load_app(application_id)
        if app.current_state_id is None:
            return None
        # Fail-closed: a vote state is decided only by the vote (or a manual abort) —
        # automatic exits are NEVER fired here even if a legacy flow still contains them;
        # the graph validator now rejects them on save. Otherwise the application would be
        # "immediately approved" without any vote.
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

    # --- branch firing ---
    async def branch_transition(
        self, application_id: UUID, branch: str
    ) -> Transition | None:
        """Find the current state's outgoing transition with ``branch``.

        ``branch`` is ``pass``/``fail`` of a ``vote`` state; ``None`` if the current
        state has no such branch exit."""
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
        """Fire the ``pass``/``fail`` transition of the current ``vote`` state.

        404 if no matching branch transition exists."""
        t = await self.branch_transition(application_id, branch)
        if t is None:
            raise NotFoundError(
                f"no '{branch}' transition from the application's current state"
            )
        return await self.fire(
            application_id, t.id, principal, note=note or branch, manual=False
        )

    async def _cancel_open_votes(self, application_id: UUID) -> None:
        """Cancel the application's open votes (``open → cancelled``)."""
        # Local import: ``voting.service`` imports FlowService — a module-level import
        # here would be a cycle.
        from app.modules.voting.models import Vote

        await self.session.execute(
            update(Vote)
            .where(Vote.application_id == application_id, Vote.status == "open")
            .values(status="cancelled")
        )

    # --- fire ---
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
        """Fire a transition. 404 (app/transition), 409 (state conflict/guard/race).

        ``deadline_passed=None`` ⇒ derive from the DB (manual paths); the deadline worker
        passes ``True`` explicitly."""
        app = await self._load_app(application_id)
        transition = await self._load_transition(transition_id)

        if transition.flow_version_id != app.flow_version_id:
            raise NotFoundError("transition does not belong to this application's flow")
        if transition.from_state_id != app.current_state_id:
            raise ConflictError(
                "Transition is not available from the current state.",
                code="conflict",
            )
        # Branch transitions (pass/fail of a vote state) are fired only by the vote
        # outcome (fire_branch, manual=False) — never directly by a user, else the vote
        # outcome could be set bypassing the vote.
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

        # --- transaction: optimistic locking via the `from`-state condition ---
        # A concurrent transition has already moved `current_state_id` → rowcount 0 →
        # 409.
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

        # Non-branch exit (manual "cancel vote" or an automatic deadline exit from a vote
        # state): the application's open votes are cancelled in the same transaction —
        # else the vote would stay open and its close() would find no branch in the new
        # state (409, open forever). Vote-outcome branches cancel nothing: close() has
        # already closed the vote there.
        if transition.branch is None:
            await self._cancel_open_votes(app.id)

        # Audit trail: record the status change append-only in the same transaction as
        # the state change (atomic). Only id references — no PII/raw note (note can be
        # free text → only presence).
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

        # Materialize the new state's deadline: if it carries a named deadline policy,
        # this creates a due deadline that the cron fires.
        to_state = await self._load_state(to_state_id)
        if to_state is not None:
            await self.session.refresh(app)
            await self.schedule_state_deadline(app, to_state)

        # --- after commit: dispatch worker actions (idempotent, retryable) ---
        dispatched = build_dispatched_actions(
            transition.actions,
            application_id=app.id,
            transition_id=transition.id,
            status_event_id=status_event_id,
        )
        # Implicit auto-mails: status update to the applicant + task mail to those who
        # may act on the new state.
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

    # --- audit-log revert ---
    async def revert_status(
        self,
        application_id: UUID,
        *,
        from_state_id: UUID,
        to_state_id: UUID,
        actor: str,
        reverted_audit_id: int,
    ) -> UUID:
        """Undo an audited status change (audit-log revert).

        Moves the application from ``to_state_id`` (the target of the change being undone)
        back to ``from_state_id`` — only if it still sits exactly in ``to_state_id``
        (else 409 ``stale_revert``; this also covers an intervening flow-version switch,
        since migrated applications then sit in a different state row). Writes a reversed
        :class:`StatusEvent` (without ``transition``) + a ``status_change`` audit entry
        (itself revertable = redo) and re-materializes the restored state's deadline. Side
        effects of the original (cancelled votes, fired webhooks/mails) are deliberately
        not undone — the revert affects only the state itself."""
        app = await self._load_app(application_id)
        if app.current_state_id != to_state_id:
            raise ConflictError(
                "A newer status change exists; revert that first.",
                code="stale_revert",
            )
        # Optimistic locking as in :meth:`fire` — a concurrent transition has already
        # moved the state → rowcount 0 → 409.
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                update(Application)
                .where(
                    Application.id == app.id,
                    Application.current_state_id == to_state_id,
                )
                .values(current_state_id=from_state_id)
            ),
        )
        if result.rowcount != 1:
            await self.session.rollback()
            raise ConflictError(
                "Concurrent status change detected; revert again.",
                code="stale_revert",
            )
        event = StatusEvent(
            application_id=app.id,
            from_state_id=to_state_id,
            to_state_id=from_state_id,
            transition_id=None,
            actor=actor,
            note="revert",
        )
        self.session.add(event)
        await self.session.flush()
        status_event_id = event.id
        # Audit as a (reversed) status_change → the revert is itself revertable (redo).
        await AuditService(self.session).record(
            actor=actor,
            action=AuditAction.STATUS_CHANGE,
            target_type="application",
            target_id=str(app.id),
            data={
                "fromStateId": str(to_state_id),
                "toStateId": str(from_state_id),
                "transitionId": None,
                "statusEventId": str(status_event_id),
                "manual": True,
                "hasNote": True,
                "reverted": True,
                "revertedAuditId": reverted_audit_id,
            },
        )
        await self.session.commit()
        # Re-materialize the restored state's deadline, like fire().
        restored_state = await self._load_state(from_state_id)
        if restored_state is not None:
            await self.session.refresh(app)
            await self.schedule_state_deadline(app, restored_state)
        return status_event_id

    # --- force status (privileged override) ---
    async def list_states(self, application_id: UUID) -> list[StateOut]:
        """All states of the application's OWN flow version (for the force-status picker).

        Scoped to ``app.flow_version_id`` — not the active global flow — so every
        returned ``id`` is a valid target for :meth:`force_status` (a state row in the
        same graph the application currently lives in; running applications may sit on an
        older flow version). Ordered initial-first, then by key for a stable list."""
        app = await self._load_app(application_id)
        states = (
            (
                await self.session.execute(
                    select(State)
                    .where(State.flow_version_id == app.flow_version_id)
                    .order_by(State.is_initial.desc(), State.key)
                )
            )
            .scalars()
            .all()
        )
        return [
            StateOut(
                id=s.id,
                key=s.key,
                label=s.label_i18n,
                color=s.color,
                editAllowed=s.edit_allowed,
                kind=s.kind,
            )
            for s in states
        ]

    async def force_status(
        self,
        application_id: UUID,
        target_state_id: UUID,
        principal: Principal,
        *,
        note: str,
    ) -> TransitionResult:
        """Force an application directly into ``target_state_id``, bypassing the flow.

        The ``application.force_status`` override: no transition, no guard, no
        ``from_state`` adjacency check. Mirrors the direct state flip of
        :meth:`revert_status` — optimistic-locked ``UPDATE``, a transition-less
        :class:`StatusEvent`, a ``status_change`` audit entry marked ``forced`` (itself
        revertable), open-vote cancellation (so a vote state left by force does not hang
        open) and deadline re-materialization. Deliberately fires NO applicant/task
        notifications or webhooks — a manual override is silent.

        404 if the target state does not belong to the application's flow; 409 if the
        application has no current state, is already in the target state, or a concurrent
        change moved it first."""
        app = await self._load_app(application_id)
        from_state_id = app.current_state_id
        if from_state_id is None:
            raise ConflictError(
                "Application has no current state to change.", code="conflict"
            )
        target = await self._load_state(target_state_id)
        if target is None or target.flow_version_id != app.flow_version_id:
            raise NotFoundError(
                "target state does not belong to this application's flow"
            )
        if target_state_id == from_state_id:
            raise ConflictError(
                "Application is already in the target state.", code="conflict"
            )
        # Optimistic locking as in fire()/revert_status — a concurrent transition has
        # already moved the state → rowcount 0 → 409.
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                update(Application)
                .where(
                    Application.id == app.id,
                    Application.current_state_id == from_state_id,
                )
                .values(current_state_id=target_state_id)
            ),
        )
        if result.rowcount != 1:
            await self.session.rollback()
            raise ConflictError(
                "Concurrent status change detected; try again.", code="conflict"
            )
        event = StatusEvent(
            application_id=app.id,
            from_state_id=from_state_id,
            to_state_id=target_state_id,
            transition_id=None,
            actor=principal.sub,
            note=note,
        )
        self.session.add(event)
        await self.session.flush()
        status_event_id = event.id
        # Leaving a (possibly vote) state by force: cancel open votes so none hangs open
        # (its close() would otherwise find no branch in the new state — open forever).
        await self._cancel_open_votes(app.id)
        # Audit as a forced status_change (id-refs only, no PII/raw note). Carries both
        # from/to state ids, so it is revertable from the audit log (undo a mistake).
        await AuditService(self.session).record(
            actor=principal.sub,
            action=AuditAction.STATUS_CHANGE,
            target_type="application",
            target_id=str(app.id),
            data={
                "fromStateId": str(from_state_id),
                "toStateId": str(target_state_id),
                "transitionId": None,
                "statusEventId": str(status_event_id),
                "manual": True,
                "hasNote": True,
                "forced": True,
            },
        )
        await self.session.commit()
        # Materialize the new state's deadline, like fire().
        to_state = await self._load_state(target_state_id)
        if to_state is not None:
            await self.session.refresh(app)
            await self.schedule_state_deadline(app, to_state)
        return TransitionResult(
            newStateId=target_state_id,
            statusEventId=status_event_id,
            dispatchedActions=[],
        )
