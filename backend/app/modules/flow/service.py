"""Flow and status engine.

Operations:

* `FlowService.available_transitions` — the manual transitions from the current state
  whose guard is `True` for the actor. Guards run server-side. Actor gates are
  fail-closed. This backs the trigger UI in the application detail view.
* `FlowService.fire` — execute a transition atomically. With `meeting_id` it also puts
  the application on the agenda of that meeting in the same transaction.
* `FlowService.auto_advance` — fire the first automatic transition whose guard holds.
  The worker or cron calls it in a cycle with `manual=False`.
* `FlowService.stage_branch` — stage the `pass` or `fail` exit of a `vote` state
  without a commit. The voting module calls it in a SAVEPOINT when it closes a vote,
  and commits the close and the transition once.
* `FlowService.start_confirmed` — start the flow of an application when its email is
  confirmed. It schedules the deadline of the current state, runs `auto_advance` and
  sends the task mail of the state.

A transition without a branch, a forced status and an audit revert leave the current
state. They cancel the votes of the application that cannot finish any more
(`VotingService.cancel_for_application`, F19 and F22). After the commit the engine
sends `vote_cancelled` for each cancelled meeting vote through the optional
`MeetingPublisher`.

Unconfirmed guest applications (`email_confirmed_at IS NULL`) rest in the flow: they get
no deadline, no automatic transition and no mail until the magic link confirms them. The
routes pass `allow_unconfirmed=False`, so such an application gives 404 there.

Edit lock: it comes from `state.edit_allowed` of the target state. The `patch` path
checks the lock and returns 409. The engine handles this inline and dispatches nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
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
    submission_anchor,
)
from app.modules.flow import context as flow_context
from app.modules.flow.dispatch import (
    ActionDispatcher,
    DispatchedAction,
    NullActionDispatcher,
    build_dispatched_actions,
    build_implicit_notifications,
)
from app.modules.flow.models import State, Transition
from app.modules.flow.schemas import TransitionOut, TransitionResult
from app.settings import get_settings
from app.shared.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationProblem,
)
from app.shared.guards import GuardContext, eval_guard, guard_requires_applicant

if TYPE_CHECKING:
    from app.modules.livevote.publisher import MeetingPublisher

logger = logging.getLogger("app.flow")


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


def agenda_gremium_id(actions: Any) -> UUID | None:
    """Return the Gremium of the first `addToNextSession` action, or `None`.

    `None` also comes back when the action holds no valid Gremium UUID. The
    transition then does not count as an agenda transition.
    """
    if not isinstance(actions, list):
        return None
    for action in actions:
        if isinstance(action, dict) and action.get("type") == "addToNextSession":
            try:
                return UUID(str(action.get("gremiumId")))
            except ValueError:
                return None
    return None


def _transition_out(t: Transition, vote_state_ids: set[UUID]) -> TransitionOut:
    """Map a transition to its API shape.

    `addsToAgenda` and `agendaGremiumId` are set only when the transition carries an
    `addToNextSession` action and its target is a vote state. Only then does a fire
    accept a `meetingId` (see `_check_agenda_meeting`), so the UI asks for a meeting
    only when the server can take one. A transition with the action into a normal
    state fires without a meeting, and the action picks the next planned meeting after
    the commit.
    """
    gremium_id = agenda_gremium_id(t.actions) if t.to_state_id in vote_state_ids else None
    return TransitionOut(
        id=t.id,
        fromStateId=t.from_state_id,
        toStateId=t.to_state_id,
        label=t.label_i18n,
        color=t.color,
        requiresAction=t.requires_action,
        addsToAgenda=gremium_id is not None,
        agendaGremiumId=gremium_id,
    )


def _meeting_problem(msg: str) -> ValidationProblem:
    return ValidationProblem(
        msg, code="agenda_meeting_invalid", errors=[{"field": "meetingId", "msg": msg}]
    )


@dataclass(frozen=True, slots=True)
class StagedFire:
    """A transition that `stage_fire` wrote into the open transaction.

    The caller commits. `after_commit` then materializes the deadline of the new
    state, publishes the cancelled votes and dispatches the actions.
    """

    application: Application
    transition: Transition
    to_state_id: UUID
    status_event_id: UUID
    # The agenda item came in the same transaction. The engine does not run the
    # `addToNextSession` action again.
    agenda_added: bool
    # The votes that the transition cancelled. Their `vote_cancelled` events go out
    # after the commit.
    cancelled_vote_ids: tuple[UUID, ...]


class FlowService:
    """Engine bound to an `AsyncSession` and an `ActionDispatcher`.

    `publisher` sends `vote_cancelled` for the meeting votes that a state change
    cancels. Without it no event goes out, and a live client sees the change on its
    next reload.
    """

    def __init__(
        self,
        session: AsyncSession,
        dispatcher: ActionDispatcher | None = None,
        publisher: MeetingPublisher | None = None,
    ) -> None:
        self.session = session
        self.dispatcher: ActionDispatcher = dispatcher or NullActionDispatcher()
        self.publisher = publisher

    async def _load_app(
        self, application_id: UUID, *, allow_unconfirmed: bool = True
    ) -> Application:
        """Load the application, or raise 404.

        `allow_unconfirmed=False` also gives 404 for an unconfirmed guest application
        (`email_confirmed_at IS NULL`). The routes use it: such an application rests in
        the flow and stays invisible, and 404 instead of 403 gives no existence oracle.
        The internal callers (worker, vote close, revert) keep the default.
        """
        app = (
            await self.session.execute(
                select(Application).where(Application.id == application_id)
            )
        ).scalar_one_or_none()
        if app is None or (not allow_unconfirmed and app.email_confirmed_at is None):
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

    async def _vote_state_ids(self, transitions: list[Transition]) -> set[UUID]:
        """Return the vote states among the targets of the agenda transitions.

        Only a transition with an `addToNextSession` action needs the kind of its
        target. Without such a transition the method does not query.
        """
        targets = {
            t.to_state_id for t in transitions if agenda_gremium_id(t.actions) is not None
        }
        if not targets:
            return set()
        rows = await self.session.execute(
            select(State.id).where(State.id.in_(targets), State.kind == "vote")
        )
        return set(rows.scalars().all())

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

    async def schedule_state_deadline(
        self,
        app: Application,
        state: State,
        *,
        commit: bool = True,
        due_at: datetime | None = None,
    ) -> Deadline | None:
        """Materialize the named deadline policy of a state that the application enters.

        A `deadlinePolicyKey` in `state.config` selects the policy. The service resolves
        it: `absolute` gives a fixed date, `relative_submitted` gives `created_at + X`
        (`received_on` + X for a captured application, see `submission_anchor`),
        and `relative_changed` gives `updated_at + X`. It then creates a `Deadline` whose
        `action_on_pass` points at the `deadlinePassed` transition of this state. The
        cron fires that transition on expiry. Without such a transition the deadline is a
        pure marker with `action_on_pass=NULL`. That marker is the basis of
        `deadlinePassed` on manual transitions (see `_deadline_passed`).

        The service always removes the flow deadlines of the state that the application
        leaves, even the consumed ones. Deadlines must not stack. A state without a
        policy must not keep a stale deadline.

        `commit=False` leaves the commit to the caller. The flow activation uses it to
        move the deadlines of all applications in its own transaction.

        `due_at` keeps a known due time and does not resolve the policy again. The flow
        activation uses it when the state keeps its `deadlinePolicyKey`. A `recurring`
        policy resolves to the next date after now, so a second resolve moves an
        expired deadline to a later date or removes it.

        Returns:
            The new deadline, or `None` when the state has no resolvable policy.
        """
        await self.session.execute(
            delete(Deadline).where(
                Deadline.application_id == app.id,
                Deadline.kind == "flow_deadline",
            )
        )
        deadline = await self._materialize_deadline(app, state, due_at=due_at)
        if commit:
            await self.session.commit()
        return deadline

    async def _materialize_deadline(
        self, app: Application, state: State, *, due_at: datetime | None = None
    ) -> Deadline | None:
        """Create the deadline row of `state` for `app`, without a commit.

        A given `due_at` replaces the due time that the policy resolves to. The policy
        must still exist.
        """
        cfg = state.config if isinstance(state.config, dict) else {}
        key = cfg.get("deadlinePolicyKey")
        if not isinstance(key, str) or not key:
            return None
        policy = await DeadlinePolicyService(self.session).get_by_key(key)
        if policy is None:
            return None
        if due_at is None:
            due_at = resolve_due_at(
                policy,
                now=datetime.now(UTC),
                submitted_at=submission_anchor(
                    app.created_at, app.received_on, get_settings().local_timezone
                ),
                changed_at=app.updated_at,
            )
        if due_at is None:
            return None
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
        return await DeadlineService(self.session).create(
            kind="flow_deadline",
            due_at=due_at,
            application_id=app.id,
            action_on_pass=(
                {"transitionId": str(target.id)} if target is not None else None
            ),
            commit=False,
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
        allow_unconfirmed: bool = True,
    ) -> list[TransitionOut]:
        """List the manual transitions the actor may fire, with the guards checked.

        The result hides automatic transitions, because the worker fires them and not the
        user. It also hides result branches, meaning transitions with `branch` set, such
        as the pass and fail exits of a vote or approval state. Only the vote decides
        those through `close_vote`, never a manual action. Actor gates in the guard refine
        which of the remaining transitions stay visible. `deadline_passed=None` means
        derive the value from the database. `allow_unconfirmed` works as in
        `_load_app`.
        """
        app = await self._load_app(application_id, allow_unconfirmed=allow_unconfirmed)
        if app.current_state_id is None:
            return []
        if deadline_passed is None:
            deadline_passed = await self._deadline_passed(app)
        ctx = await flow_context.build_context(
            self.session, app, principal, manual=True, deadline_passed=deadline_passed
        )
        visible = [
            t
            for t in await self._outgoing(app)
            if not t.automatic and not t.branch and eval_guard(t.guard, ctx)
        ]
        vote_ids = await self._vote_state_ids(visible)
        return [_transition_out(t, vote_ids) for t in visible]

    _APPLICANT = Principal(sub="applicant", roles=[], permissions=set())

    async def available_applicant_transitions(
        self, application_id: UUID, *, allow_unconfirmed: bool = True
    ) -> list[TransitionOut]:
        """List the transitions the magic-link applicant may fire.

        A transition qualifies when it is manual, when its guard holds in the applicant
        context, and when `actorIsApplicant` opens it. Nothing else qualifies. There is
        no implicit applicant access. `allow_unconfirmed` works as in `_load_app`.
        """
        app = await self._load_app(application_id, allow_unconfirmed=allow_unconfirmed)
        if app.current_state_id is None:
            return []
        ctx = await flow_context.build_context(
            self.session, app, self._APPLICANT, manual=True, as_applicant=True
        )
        visible = [
            t
            for t in await self._outgoing(app)
            if not t.automatic
            and not t.branch
            and guard_requires_applicant(t.guard)
            and eval_guard(t.guard, ctx)
        ]
        vote_ids = await self._vote_state_ids(visible)
        return [_transition_out(t, vote_ids) for t in visible]

    async def fire_as_applicant(
        self,
        application_id: UUID,
        transition_id: UUID,
        *,
        note: str | None = None,
        allow_unconfirmed: bool = True,
    ) -> TransitionResult:
        """Fire a transition as the applicant.

        Only a manual transition that `actorIsApplicant` opens may fire. Every other
        transition gives 403. This path bypasses the `application.manage` gate on
        purpose, but only for the transitions that the admin opened.
        `allow_unconfirmed` works as in `_load_app`.
        """
        transition = await self._load_transition(transition_id)
        if transition.automatic or not guard_requires_applicant(transition.guard):
            raise ForbiddenError("transition is not open to the applicant")
        return await self.fire(
            application_id,
            transition_id,
            self._APPLICANT,
            note=note,
            as_applicant=True,
            allow_unconfirmed=allow_unconfirmed,
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

    # Actor of the automatic transitions that a confirmation starts. No user stands
    # behind it. It has the roles and permissions of the cron actor, so a guard gives
    # the same result on both paths.
    _SYSTEM = Principal(
        sub="system:confirmation", roles=["system"], permissions={"application.manage"}
    )

    async def start_confirmed(self, application_id: UUID) -> TransitionResult | None:
        """Start the flow of an application whose email is confirmed.

        An unconfirmed guest application rests in the flow. The magic-link verify
        confirms it and then calls this method one time. A logged-in submission is
        confirmed at once, so the create calls this method directly. The method runs
        three steps:

        1. Schedule the deadline of the current state. This also deletes the stale
           flow deadlines of the application.
        2. Run `auto_advance`.
        3. When no transition fired, send the task mail of the current state to the
           people who can act there. A fired transition sends its own mails.

        Step 1 commits the confirmation. After that commit, an error in step 2 or 3
        must not fail the verify or the create request: the email is confirmed, a
        single-use link is spent, and a logged-in create already has its
        application. So, as in the cron, the method catches every error of steps 2
        and 3, rolls the session back and writes a log line. A `ConflictError` or a
        `NotFoundError` is an expected race and gets an info line. Every other error
        gets a log line with the traceback. The cron tries the automatic transitions
        again.

        The idempotency key of the task mail holds the id of the latest status event.
        A second call therefore sends no second mail.

        Returns:
            The result of the automatic transition, or `None` when none fired.
        """
        app = await self._load_app(application_id)
        if app.current_state_id is None:
            return None
        state = await self._load_state(app.current_state_id)
        if state is not None:
            await self.schedule_state_deadline(app, state)
        else:
            # The dispatchers read in their own sessions. Commit the confirmation
            # first, so that they see the application as confirmed.
            await self.session.commit()
        try:
            fired = await self.auto_advance(application_id, self._SYSTEM)
            if fired is None:
                await self._announce_current_state(application_id)
        except (ConflictError, NotFoundError) as exc:
            await self.session.rollback()
            logger.info(
                "auto-transition on confirmation skipped (app=%s): %s", application_id, exc
            )
            return None
        except Exception:  # noqa: BLE001 - a failed start must not fail the committed confirmation
            # Roll back the failed step, so the caller can still use the session (the
            # verify commits, the create refreshes the application).
            await self.session.rollback()
            logger.exception("flow start on confirmation failed (app=%s)", application_id)
            return None
        return fired

    async def _announce_current_state(self, application_id: UUID) -> None:
        """Send the task mail of the current state, keyed on the latest status event.

        The notify dispatcher resolves the recipients at send time. It sends nothing
        when the state is not actionable or nobody can act there.
        """
        status_event_id = await self.session.scalar(
            select(StatusEvent.id)
            .where(StatusEvent.application_id == application_id)
            .order_by(StatusEvent.at.desc())
            .limit(1)
        )
        if status_event_id is None:
            return
        await self.dispatcher.dispatch(
            [
                DispatchedAction(
                    type="taskNotify",
                    application_id=application_id,
                    transition_id=None,
                    status_event_id=status_event_id,
                    idempotency_key=f"{application_id}:{status_event_id}:auto:task",
                )
            ]
        )

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
        """Fire the `pass` or `fail` transition of the current `vote` state and commit.

        The vote close does not use this method. It stages the branch with
        `stage_branch` in a SAVEPOINT and commits the close once.

        Raises:
            NotFoundError: No matching branch transition exists (404).
            ConflictError: The guard fails, or another transition won the race (409).
        """
        staged = await self.stage_branch(
            application_id, branch, principal, note=note, rollback_on_conflict=True
        )
        await self.session.commit()
        return await self.after_commit(staged)

    async def stage_branch(
        self,
        application_id: UUID,
        branch: str,
        principal: Principal,
        *,
        note: str | None = None,
        rollback_on_conflict: bool = False,
    ) -> StagedFire:
        """Stage the `pass` or `fail` transition of the current `vote` state.

        The method does not commit. By default it does not roll back either: the voting
        module runs it in a SAVEPOINT (`session.begin_nested()`). On an error only the
        SAVEPOINT rolls back, and the vote close still commits (F20). After the commit
        the caller runs `after_commit`.

        Raises:
            NotFoundError: No matching branch transition exists (404).
            ConflictError: The guard fails, or another transition won the race (409).
        """
        t = await self.branch_transition(application_id, branch)
        if t is None:
            raise NotFoundError(
                f"no '{branch}' transition from the application's current state"
            )
        return await self.stage_fire(
            application_id,
            t.id,
            principal,
            note=note or branch,
            manual=False,
            rollback_on_conflict=rollback_on_conflict,
        )

    async def _cancel_votes(
        self,
        application_id: UUID,
        *,
        actor: str,
        left_state_id: UUID | None,
        entered_state_id: UUID | None,
    ) -> tuple[UUID, ...]:
        """Cancel the votes of the application that the state change orphans.

        The votes are the open votes and the drafts of the state that the application
        leaves (see `VotingService.cancel_for_application`). The other drafts stay. The
        method does not commit.

        Returns:
            The ids of the cancelled votes.
        """
        # Local import: `voting.service` imports FlowService. A module-level import here
        # would create a cycle.
        from app.modules.voting.service import VotingService

        votes = await VotingService(self.session).cancel_for_application(
            application_id,
            now=datetime.now(UTC),
            actor=actor,
            left_state_id=left_state_id,
            entered_state_id=entered_state_id,
        )
        return tuple(v.id for v in votes)

    async def _publish_cancelled(self, vote_ids: tuple[UUID, ...]) -> None:
        """Send `vote_cancelled` for each cancelled vote, after the commit.

        The publisher drops a vote without a meeting. A broker fault must not fail
        the committed state change, so the method only logs it.
        """
        if self.publisher is None or not vote_ids:
            return
        from app.modules.voting.service import VotingService

        voting = VotingService(self.session)
        for vote_id in vote_ids:
            try:
                await self.publisher.vote_cancelled(await voting.get(vote_id))
            except Exception:  # noqa: BLE001 - the broadcast is best effort
                logger.warning("vote_cancelled broadcast failed (vote=%s)", vote_id)

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
        meeting_id: UUID | None = None,
        non_public: bool = False,
        allow_unconfirmed: bool = True,
    ) -> TransitionResult:
        """Fire a transition.

        `deadline_passed=None` means derive the value from the database, as the manual
        paths do. The deadline worker passes `True` on its own.

        `meeting_id` puts the application on the agenda of that meeting. The engine
        checks the meeting before the state change: the principal can read it, it is
        `planned`, its Gremium is the Gremium of the `addToNextSession` action of the
        transition, and the target state is a vote state. The agenda item then comes
        in the same transaction as the state change, with `non_public` as its
        visibility. The `addToNextSession` action does not run again after the commit.

        `allow_unconfirmed` works as in `_load_app`.

        Raises:
            NotFoundError: The application or the transition does not exist (404).
            ConflictError: The state does not match, the guard fails, or another
                transition won the race (409).
            ValidationProblem: `meeting_id` does not fit the transition (422).
        """
        staged = await self.stage_fire(
            application_id,
            transition_id,
            principal,
            note=note,
            deadline_passed=deadline_passed,
            manual=manual,
            as_applicant=as_applicant,
            meeting_id=meeting_id,
            non_public=non_public,
            allow_unconfirmed=allow_unconfirmed,
        )
        await self.session.commit()
        return await self.after_commit(staged)

    async def stage_fire(
        self,
        application_id: UUID,
        transition_id: UUID,
        principal: Principal,
        *,
        note: str | None = None,
        deadline_passed: bool | None = None,
        manual: bool = True,
        as_applicant: bool = False,
        meeting_id: UUID | None = None,
        non_public: bool = False,
        allow_unconfirmed: bool = True,
        rollback_on_conflict: bool = True,
    ) -> StagedFire:
        """Write a transition into the open transaction, without a commit.

        `fire` documents the arguments. `rollback_on_conflict=False` leaves a lost race
        to the caller: the voting close runs this in a SAVEPOINT, and a full rollback
        there would also drop the staged vote close.

        Raises:
            NotFoundError: The application or the transition does not exist (404).
            ConflictError: The state does not match, the guard fails, or another
                transition won the race (409).
            ValidationProblem: `meeting_id` does not fit the transition (422).
        """
        app = await self._load_app(application_id, allow_unconfirmed=allow_unconfirmed)
        transition = await self._load_transition(transition_id)

        if transition.flow_version_id != app.flow_version_id:
            raise NotFoundError("transition does not belong to this application's flow")
        if transition.from_state_id != app.current_state_id:
            raise ConflictError(
                "Transition is not available from the current state.",
                code="conflict",
            )
        # Only the vote outcome fires a branch transition, the pass or fail exit of a
        # vote state. It arrives through stage_branch with manual=False. A user must
        # never fire one directly, because that would set the vote outcome without a
        # vote.
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
        if meeting_id is not None:
            await self._check_agenda_meeting(transition, meeting_id, principal)

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
            if rollback_on_conflict:
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
        # vote state. It cancels the open and draft votes of the application in the
        # same transaction (F19). Otherwise a vote would stay open and its close()
        # would find no branch in the new state, and a draft could open later outside
        # its vote state. A vote-outcome branch cancels nothing, because close()
        # already closed the vote.
        cancelled: tuple[UUID, ...] = ()
        if transition.branch is None:
            cancelled = await self._cancel_votes(
                app.id,
                actor=principal.sub,
                left_state_id=from_state_id,
                entered_state_id=to_state_id,
            )

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
        if meeting_id is not None:
            await self._add_to_agenda_in_tx(
                app.id, meeting_id, non_public=non_public, actor=principal.sub
            )
        return StagedFire(
            application=app,
            transition=transition,
            to_state_id=to_state_id,
            status_event_id=status_event_id,
            agenda_added=meeting_id is not None,
            cancelled_vote_ids=cancelled,
        )

    async def schedule_staged_deadline(
        self, staged: StagedFire, *, commit: bool = True
    ) -> None:
        """Materialize the deadline of the state that a staged transition enters.

        If the state carries a named deadline policy, this creates a due deadline that
        the cron fires. `commit=False` keeps it in the open transaction, so the vote
        close commits it together with the transition.
        """
        to_state = await self._load_state(staged.to_state_id)
        if to_state is not None:
            await self.session.refresh(staged.application)
            await self.schedule_state_deadline(staged.application, to_state, commit=commit)

    async def after_commit(
        self, staged: StagedFire, *, schedule_deadline: bool = True
    ) -> TransitionResult:
        """Run the work that follows the commit of a staged transition.

        The work is the deadline of the new state (unless the caller already staged
        it, `schedule_deadline=False`), the `vote_cancelled` events and the worker
        actions. The actions are idempotent and retryable.
        """
        if schedule_deadline:
            await self.schedule_staged_deadline(staged)
        await self._publish_cancelled(staged.cancelled_vote_ids)
        transition = staged.transition
        app_id = staged.application.id
        dispatched = build_dispatched_actions(
            transition.actions,
            application_id=app_id,
            transition_id=transition.id,
            status_event_id=staged.status_event_id,
        )
        if staged.agenda_added:
            # The agenda item is already in place. Do not add it a second time.
            dispatched = [a for a in dispatched if a.type != "addToNextSession"]
        dispatched += build_implicit_notifications(
            transition.actions,
            application_id=app_id,
            transition_id=transition.id,
            status_event_id=staged.status_event_id,
        )
        await self.dispatcher.dispatch(dispatched)

        return TransitionResult(
            newStateId=staged.to_state_id,
            statusEventId=staged.status_event_id,
            dispatchedActions=[a.type for a in dispatched],
        )

    async def _check_agenda_meeting(
        self, transition: Transition, meeting_id: UUID, principal: Principal
    ) -> None:
        """Check the meeting that a manual fire picks for the agenda item.

        Raises:
            ValidationProblem: The transition has no `addToNextSession` action, its
                target is not a vote state, or the meeting is unknown, not readable,
                not `planned` or of another Gremium (422).
        """
        # Local import: `livevote` imports the voting module, and that imports
        # FlowService. A module-level import here would create a cycle.
        from app.modules.livevote.models import Meeting
        from app.modules.livevote.service import MeetingService

        gremium_id = agenda_gremium_id(transition.actions)
        if gremium_id is None:
            raise _meeting_problem("This transition does not add to an agenda.")
        to_state = await self._load_state(transition.to_state_id)
        if to_state is None or to_state.kind != "vote":
            raise _meeting_problem("The target state of this transition is no vote state.")
        try:
            await MeetingService(self.session).assert_can_read(meeting_id, principal)
        except (NotFoundError, ForbiddenError) as exc:
            raise _meeting_problem("The meeting is unknown or not visible.") from exc
        meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None or meeting.status != "planned":
            raise _meeting_problem("The meeting is not planned.")
        if meeting.gremium_id != gremium_id:
            raise _meeting_problem("The meeting belongs to another Gremium.")

    async def _add_to_agenda_in_tx(
        self, application_id: UUID, meeting_id: UUID, *, non_public: bool, actor: str
    ) -> None:
        """Add the agenda item in the open transaction. Roll back on a refusal."""
        from app.modules.livevote.agenda_service import AgendaService

        try:
            await AgendaService(self.session).add_in_tx(
                meeting_id, application_id=application_id, non_public=non_public, actor=actor
            )
        except (NotFoundError, ConflictError) as exc:
            await self.session.rollback()
            raise _meeting_problem(
                "The application cannot go on the agenda of this meeting."
            ) from exc

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
        deadline of the restored state.

        The application leaves `to_state_id`, so the method cancels its votes like a
        transition without a branch does (F22): the open votes and the draft votes that
        do not belong to the restored state. Otherwise a vote of an undone vote state
        stays open, and every close gives 409. The method deliberately undoes no other
        side effect of the original change: a cancelled vote stays cancelled, and fired
        webhooks and mails stay sent.

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
        cancelled = await self._cancel_votes(
            app.id,
            actor=actor,
            left_state_id=to_state_id,
            entered_state_id=from_state_id,
        )
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
        await self._publish_cancelled(cancelled)
        return status_event_id

    async def list_states(
        self, application_id: UUID, *, allow_unconfirmed: bool = True
    ) -> list[StateOut]:
        """List all states of the own flow version of the application.

        The force-status picker uses this list. The query is scoped to
        `app.flow_version_id` and not to the active global flow. Every returned `id` is
        therefore a valid target for `force_status`. It is a state row in the same graph
        that the application lives in. A running application may sit on an older flow
        version. The order is initial-first, then by key, which keeps the list stable.
        `allow_unconfirmed` works as in `_load_app`.
        """
        app = await self._load_app(application_id, allow_unconfirmed=allow_unconfirmed)
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
        allow_unconfirmed: bool = True,
    ) -> TransitionResult:
        """Force an application directly into `target_state_id` and bypass the flow.

        This is the `application.force_status` override. It uses no transition, no guard
        and no `from_state` adjacency check. It mirrors the direct state flip of
        `revert_status`: an optimistic-locked `UPDATE`, a `StatusEvent` without a
        transition, and a `status_change` audit entry marked `forced`. That audit entry
        is itself revertable. The method also cancels the open votes and the draft votes
        that do not belong to the target state (F19), so a vote state that you leave by
        force does not hang open. It then re-materializes the deadline and sends
        `vote_cancelled` for the cancelled meeting votes.
        It deliberately sends no applicant notification and no task notification, and it
        fires no webhook. A manual override stays silent. `allow_unconfirmed` works as
        in `_load_app`.

        Raises:
            NotFoundError: The target state does not belong to the flow of the
                application (404).
            ConflictError: The application has no current state, already sits in the
                target state, or a concurrent change moved it first (409).
        """
        app = await self._load_app(application_id, allow_unconfirmed=allow_unconfirmed)
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
        # state and the vote would stay open forever. Cancel the drafts of the old
        # state too, so that none opens later outside its vote state.
        cancelled = await self._cancel_votes(
            app.id,
            actor=principal.sub,
            left_state_id=from_state_id,
            entered_state_id=target_state_id,
        )
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
        await self._publish_cancelled(cancelled)
        return TransitionResult(
            newStateId=target_state_id,
            statusEventId=status_event_id,
            dispatchedActions=[],
        )
