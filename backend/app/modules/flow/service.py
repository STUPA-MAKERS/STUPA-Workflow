"""Flow and status engine.

Operations:

* `FlowService.available_transitions` — the manual transitions from the current state
  whose guard is `True` for the actor. Guards run server-side. Actor gates are
  fail-closed. This backs the trigger UI in the application detail view.
* `FlowService.fire` — execute a transition atomically.
* `FlowService.auto_advance` — fire the first automatic transition whose guard holds.
  The worker or cron calls it in a cycle with `manual=False`.
* `FlowService.fire_branch` — fire the `pass` or `fail` exit of a `vote` state. The
  voting module calls it when it closes a vote.

Edit lock: it comes from `state.edit_allowed` of the target state. The `patch` path
checks the lock and returns 409. The engine handles this inline and dispatches nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
    """Report whether the guard must fire on an expired deadline.

    The check walks `and`, `or` and `not` recursively. The guard qualifies when it needs
    `deadlinePassed` to be true under the current negation polarity. So
    `{deadlinePassed: true}` and `not(deadlinePassed: false)` count, but
    `not(deadlinePassed: true)` does not.
    """
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
    """Engine bound to an `AsyncSession` and an `ActionDispatcher`."""

    def __init__(
        self, session: AsyncSession, dispatcher: ActionDispatcher | None = None
    ) -> None:
        self.session = session
        self.dispatcher: ActionDispatcher = dispatcher or NullActionDispatcher()

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

    async def schedule_state_deadline(self, app: Application, state: State) -> None:
        """Materialize the named deadline policy of a state that the application enters.

        A `deadlinePolicyKey` in `state.config` selects the policy. The service resolves
        it: `absolute` gives a fixed date, `relative_submitted` gives `created_at + X`,
        and `relative_changed` gives `updated_at + X`. It then creates a `Deadline` whose
        `action_on_pass` points at the `deadlinePassed` transition of this state. The
        cron fires that transition on expiry. Without such a transition the deadline is a
        pure marker with `action_on_pass=NULL`. That marker is the basis of
        `deadlinePassed` on manual transitions (see `_deadline_passed`).

        The service always removes the flow deadlines of the state that the application
        leaves, even the consumed ones. Deadlines must not stack. A state without a
        policy must not keep a stale deadline.
        """
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
            policy,
            now=datetime.now(UTC),
            submitted_at=app.created_at,
            changed_at=app.updated_at,
        )
        if due_at is None:
            await self.session.commit()
            return
        # The target is the outgoing transition of the state that must fire on an expired
        # deadline, under the `deadlinePassed` polarity including negation. With several
        # candidates, take the one with the smallest `order` for a deterministic result.
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

    # Minimal context: only the deadline counts as satisfied. There are no roles, no
    # budget fit and no field values. A candidate whose full guard is already `True` here
    # needs nothing but the expired deadline, so it fires on expiry for sure. This stays
    # evaluable without I/O at schedule time.
    _DEADLINE_ONLY_CTX = GuardContext(manual=False, deadline_passed=True)

    @classmethod
    def _pick_deadline_transition(
        cls, candidates: list[Transition]
    ) -> Transition | None:
        """Pick the first `deadlinePassed` candidate that the expired deadline alone opens.

        The candidates come in `order`. A candidate whose guard holds under
        `_DEADLINE_ONLY_CTX` (only `deadline_passed=True`, everything else empty) fires
        on expiry for sure. A candidate with an extra AND predicate would not fire. The
        cron would still consume the deadline (`ConflictError` leads to
        `action_on_pass=NULL`) and the application would hang without a deadline. If no
        candidate holds without an extra condition, pin the first one as a pure marker.
        The deadline then stays visible.
        """
        if not candidates:
            return None
        for t in candidates:
            if eval_guard(t.guard, cls._DEADLINE_ONLY_CTX):
                return t
        return candidates[0]

    async def _deadline_passed(self, app: Application) -> bool:
        """Derive the real `deadline_passed` of the current state from the database.

        The work goes to `flow_deadline_passed` in the deadlines service. The task-mail
        recipient resolution uses the same derivation.
        """
        return await flow_deadline_passed(self.session, app.id)

    async def available_transitions(
        self,
        application_id: UUID,
        principal: Principal,
        *,
        deadline_passed: bool | None = None,
    ) -> list[TransitionOut]:
        """List the manual transitions the actor may fire, with the guards checked.

        The result hides automatic transitions, because the worker fires them and not the
        user. It also hides result branches, meaning transitions with `branch` set, such
        as the pass and fail exits of a vote or approval state. Only the vote decides
        those through `close_vote`, never a manual action. Actor gates in the guard refine
        which of the remaining transitions stay visible. `deadline_passed=None` means
        derive the value from the database.
        """
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

    _APPLICANT = Principal(sub="applicant", roles=[], permissions=set())

    async def available_applicant_transitions(
        self, application_id: UUID
    ) -> list[TransitionOut]:
        """List the transitions the magic-link applicant may fire.

        A transition qualifies when it is manual, when its guard holds in the applicant
        context, and when `actorIsApplicant` opens it. Nothing else qualifies. There is
        no implicit applicant access.
        """
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
        """Fire a transition as the applicant.

        Only a manual transition that `actorIsApplicant` opens may fire. Every other
        transition gives 403. This path bypasses the `application.manage` gate on
        purpose, but only for the transitions that the admin opened.
        """
        transition = await self._load_transition(transition_id)
        if transition.automatic or not guard_requires_applicant(transition.guard):
            raise ForbiddenError("transition is not open to the applicant")
        return await self.fire(
            application_id, transition_id, self._APPLICANT, note=note, as_applicant=True
        )

    async def auto_advance(
        self,
        application_id: UUID,
        principal: Principal,
        *,
        deadline_passed: bool | None = None,
    ) -> TransitionResult | None:
        """Fire the first automatic transition whose guard holds.

        The worker or cron calls this in a cycle with `manual=False`. The optimistic
        locking in `fire` keeps it idempotent. `deadline_passed=None` means derive the
        value from the database.

        Returns:
            The result of the fired transition, or `None` when none fired.
        """
        app = await self._load_app(application_id)
        if app.current_state_id is None:
            return None
        # Fail-closed: only the vote or a manual abort decides a vote state. This code
        # never fires an automatic exit from a vote state, even when a legacy flow still
        # holds one. The graph validator rejects such an exit on save. Otherwise the
        # application would be approved at once without any vote.
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

    async def branch_transition(
        self, application_id: UUID, branch: str
    ) -> Transition | None:
        """Find the outgoing transition of the current state with `branch`.

        `branch` is `pass` or `fail` of a `vote` state. The result is `None` when the
        current state has no such branch exit.
        """
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
        """Fire the `pass` or `fail` transition of the current `vote` state.

        Raises:
            NotFoundError: No matching branch transition exists (404).
        """
        t = await self.branch_transition(application_id, branch)
        if t is None:
            raise NotFoundError(
                f"no '{branch}' transition from the application's current state"
            )
        return await self.fire(
            application_id, t.id, principal, note=note or branch, manual=False
        )

    async def _cancel_open_votes(self, application_id: UUID) -> None:
        """Cancel the open votes of the application (`open` becomes `cancelled`)."""
        # Local import: `voting.service` imports FlowService. A module-level import here
        # would create a cycle.
        from app.modules.voting.models import Vote

        await self.session.execute(
            update(Vote)
            .where(Vote.application_id == application_id, Vote.status == "open")
            .values(status="cancelled")
        )

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
        """Fire a transition.

        `deadline_passed=None` means derive the value from the database, as the manual
        paths do. The deadline worker passes `True` on its own.

        Raises:
            NotFoundError: The application or the transition does not exist (404).
            ConflictError: The state does not match, the guard fails, or another
                transition won the race (409).
        """
        app = await self._load_app(application_id)
        transition = await self._load_transition(transition_id)

        if transition.flow_version_id != app.flow_version_id:
            raise NotFoundError("transition does not belong to this application's flow")
        if transition.from_state_id != app.current_state_id:
            raise ConflictError(
                "Transition is not available from the current state.",
                code="conflict",
            )
        # Only the vote outcome fires a branch transition, the pass or fail exit of a
        # vote state. It arrives through fire_branch with manual=False. A user must never
        # fire one directly, because that would set the vote outcome without a vote.
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

        # Optimistic locking through the `from`-state condition. A concurrent transition
        # has already moved `current_state_id`, so rowcount is 0 and the caller gets 409.
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

        # A non-branch exit is a manual vote cancel or an automatic deadline exit from a
        # vote state. It cancels the open votes of the application in the same
        # transaction. Otherwise a vote would stay open and its close() would find no
        # branch in the new state, which gives 409 and an open vote forever. A
        # vote-outcome branch cancels nothing, because close() already closed the vote.
        if transition.branch is None:
            await self._cancel_open_votes(app.id)

        # Audit trail: record the status change append-only in the same transaction as
        # the state change, so both stay atomic. The entry holds id references only, no
        # PII and no raw note. A note is free text, so the entry keeps only its presence.
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

        # Materialize the deadline of the new state. If the state carries a named
        # deadline policy, this creates a due deadline that the cron fires.
        to_state = await self._load_state(to_state_id)
        if to_state is not None:
            await self.session.refresh(app)
            await self.schedule_state_deadline(app, to_state)

        # After the commit: dispatch the worker actions. They are idempotent and
        # retryable.
        dispatched = build_dispatched_actions(
            transition.actions,
            application_id=app.id,
            transition_id=transition.id,
            status_event_id=status_event_id,
        )
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

        The method moves the application from `to_state_id`, the target of the change
        that you undo, back to `from_state_id`. It does so only while the application
        still sits exactly in `to_state_id`. Otherwise it raises 409 `stale_revert`. That
        check also covers a flow-version switch in between, because a migrated
        application then sits in a different state row. The method writes a reversed
        `StatusEvent` without a transition and a `status_change` audit entry. That entry
        is itself revertable, which gives a redo. The method also re-materializes the
        deadline of the restored state. It deliberately undoes no side effect of the
        original change, such as cancelled votes or fired webhooks and mails. The revert
        touches only the state.

        Returns:
            The id of the new status event.
        """
        app = await self._load_app(application_id)
        if app.current_state_id != to_state_id:
            raise ConflictError(
                "A newer status change exists; revert that first.",
                code="stale_revert",
            )
        # Optimistic locking as in `fire`. A concurrent transition has already moved the
        # state, so rowcount is 0 and the caller gets 409.
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
        # Audit as a reversed status_change, so the revert is itself revertable (redo).
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
        # Re-materialize the deadline of the restored state, as fire() does.
        restored_state = await self._load_state(from_state_id)
        if restored_state is not None:
            await self.session.refresh(app)
            await self.schedule_state_deadline(app, restored_state)
        return status_event_id

    async def list_states(self, application_id: UUID) -> list[StateOut]:
        """List all states of the own flow version of the application.

        The force-status picker uses this list. The query is scoped to
        `app.flow_version_id` and not to the active global flow. Every returned `id` is
        therefore a valid target for `force_status`. It is a state row in the same graph
        that the application lives in. A running application may sit on an older flow
        version. The order is initial-first, then by key, which keeps the list stable.
        """
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
        """Force an application directly into `target_state_id` and bypass the flow.

        This is the `application.force_status` override. It uses no transition, no guard
        and no `from_state` adjacency check. It mirrors the direct state flip of
        `revert_status`: an optimistic-locked `UPDATE`, a `StatusEvent` without a
        transition, and a `status_change` audit entry marked `forced`. That audit entry
        is itself revertable. The method also cancels the open votes, so a vote state
        that you leave by force does not hang open. It then re-materializes the deadline.
        It deliberately sends no applicant notification and no task notification, and it
        fires no webhook. A manual override stays silent.

        Raises:
            NotFoundError: The target state does not belong to the flow of the
                application (404).
            ConflictError: The application has no current state, already sits in the
                target state, or a concurrent change moved it first (409).
        """
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
        # Optimistic locking as in fire() and revert_status. A concurrent transition has
        # already moved the state, so rowcount is 0 and the caller gets 409.
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
        # The force leaves a state that may be a vote state. Cancel the open votes so
        # that none hangs open. Its close() would otherwise find no branch in the new
        # state and the vote would stay open forever.
        await self._cancel_open_votes(app.id)
        # Audit as a forced status_change with id references only, no PII and no raw
        # note. The entry carries both state ids, so the audit log can revert it and undo
        # a mistake.
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
        # Materialize the deadline of the new state, as fire() does.
        to_state = await self._load_state(target_state_id)
        if to_state is not None:
            await self.session.refresh(app)
            await self.schedule_state_deadline(app, to_state)
        return TransitionResult(
            newStateId=target_state_id,
            statusEventId=status_event_id,
            dispatchedActions=[],
        )
