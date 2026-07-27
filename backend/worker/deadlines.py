"""arq cron task: scheduled deadline and vote processing.

`process_deadlines` runs every minute against a tz-aware `now` in UTC. It runs these
idempotent steps:

1. Reminders. A deadline inside or past the lead window with no reminder yet gets
   `notify(deadline_approaching)` and a `reminded_at` timestamp, exactly once. There
   is no lower bound: after an outage longer than the lead window the reminder is
   late but still fires only once.
2. Auto-transitions and requeue. An expired deadline with `action_on_pass` calls
   `flow.fire` with the `deadlinePassed` guard and `manual=False`. The task then
   clears `action_on_pass` as the idempotency marker. `kind="requeue"` returns the
   application through the referenced transition.
3. Vote auto-close. An open vote past `closes_at` goes to `voting.close`, which
   tallies the vote and fires the result branch.

Concurrency: each unit gets a lock in its own session with `FOR UPDATE SKIP LOCKED`.
A second worker skips a locked unit, so nothing runs twice. The operations are also
idempotent by themselves: `flow.fire` uses optimistic locking, `voting.close` checks
the status, and the mail enqueue deduplicates on `_job_id`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.deadlines.service import (
    DEFAULT_SCAN_LIMIT,
    DeadlineService,
    transition_ref,
)
from app.modules.flow.models import Transition
from app.modules.flow.service import FlowService
from app.modules.livevote.broker import RedisBroker
from app.modules.livevote.service import BrokerPublisher
from app.modules.notifications.action_dispatcher import build_notify_dispatcher
from app.modules.notifications.queue import ArqMailQueue, MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.voting.schemas import VoteClosed
from app.modules.voting.service import VotingService
from app.settings import Settings, load_settings
from app.shared.errors import ConflictError, NotFoundError

logger = logging.getLogger("app.deadlines")

# The worker deletes guest applications without email confirmation after this window.
_GUEST_CONFIRM_TTL = timedelta(hours=12)


async def on_startup(ctx: dict[str, Any]) -> None:
    ctx["settings"] = load_settings()


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via `ctx['deadlines_sessionmaker']`)."""
    maker = ctx.get("deadlines_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _now() -> datetime:
    """Return the current tz-aware UTC time (tests control it with freezegun)."""
    return datetime.now(UTC)


def _system_principal() -> Principal:
    """Build the actor for cron-triggered transitions.

    No user stands behind this principal. `application.manage` covers the role guards
    on the requeue and result branches.
    """
    return Principal(
        sub="system:deadlines",
        roles=["system"],
        permissions={"application.manage"},
    )


def _mail_queue(ctx: dict[str, Any]) -> MailQueue | None:
    """Return the mail queue over the arq Redis pool, or `None` without Redis.

    Tests can inject a ready queue through `ctx['mail_queue']`.
    """
    queue = ctx.get("mail_queue")
    if queue is not None:
        return queue  # type: ignore[return-value]
    pool = ctx.get("redis")
    return ArqMailQueue(pool) if pool is not None else None


async def process_deadlines(ctx: dict[str, Any]) -> str:
    """Run reminders, auto-transitions and vote auto-close (idempotent, SKIP LOCKED)."""
    settings: Settings = ctx.get("settings") or load_settings()
    now = _now()
    reminded = await _process_reminders(ctx, settings, now)
    fired = await _process_actions(ctx, settings, now)
    closed = await _process_votes(ctx, now)
    advanced = await _process_auto_transitions(ctx)
    discarded = await _discard_unconfirmed(ctx, now)
    return (
        f"reminders={reminded} actions={fired} votes={closed} "
        f"auto={advanced} discarded={discarded}"
    )


async def _discard_unconfirmed(ctx: dict[str, Any], now: datetime) -> int:
    """Delete guest applications that stay unconfirmed past the TTL window.

    The delete covers only anonymous (`created_by IS NULL`) and unconfirmed
    (`email_confirmed_at IS NULL`) applications older than the TTL. Rows that depend
    on them through a foreign key cascade. The step is idempotent, so a second run
    finds nothing.
    """
    maker = _sessionmaker(ctx)
    cutoff = now - _GUEST_CONFIRM_TTL
    async with maker() as session:
        result = cast(
            "CursorResult[Any]",
            await session.execute(
                delete(Application).where(
                    Application.created_by.is_(None),
                    Application.email_confirmed_at.is_(None),
                    Application.created_at < cutoff,
                )
            ),
        )
        await session.commit()
    discarded = result.rowcount or 0
    if discarded:
        logger.info("discarded %d unconfirmed guest application(s)", discarded)
    return discarded


async def _process_reminders(
    ctx: dict[str, Any], settings: Settings, now: datetime
) -> int:
    maker = _sessionmaker(ctx)
    lead = timedelta(minutes=settings.deadline_reminder_lead_minutes)
    async with maker() as session:
        ids = await DeadlineService(session).due_reminder_ids(now, lead)
    sent = 0
    for deadline_id in ids:
        try:
            if await _remind_one(ctx, settings, deadline_id, now, lead):
                sent += 1
        except Exception:  # noqa: BLE001 - one broken deadline must not abort the cycle
            logger.exception("deadline reminder failed (deadline=%s)", deadline_id)
    return sent


async def _remind_one(
    ctx: dict[str, Any],
    settings: Settings,
    deadline_id: UUID,
    now: datetime,
    lead: timedelta,
) -> bool:
    maker = _sessionmaker(ctx)
    queue = _mail_queue(ctx)
    async with maker() as session:
        svc = DeadlineService(session)
        deadline = await svc.lock_reminder(deadline_id, now, lead)
        if deadline is None:
            return False  # another worker holds it, or it is no longer due
        type_id = deadline.type_id
        if type_id is None and deadline.application_id is not None:
            type_id = await session.scalar(
                select(Application.type_id).where(
                    Application.id == deadline.application_id
                )
            )
        notifier = NotificationService(session, queue=queue, settings=settings)
        await notifier.handle_notify_action(
            {"templateKey": "deadline_approaching", "recipients": [{"kind": "applicant"}]},
            application_id=deadline.application_id,
            application_type_id=type_id,
            context={
                "deadlineId": str(deadline.id),
                "kind": deadline.kind,
                "dueAt": deadline.due_at.isoformat(),
            },
            lang=None,
            idempotency_base=f"deadline:{deadline.id}",
        )
        await svc.mark_reminded(deadline, now)
    logger.info("deadline reminder sent (deadline=%s kind=%s)", deadline_id, deadline.kind)
    return True


async def _process_actions(
    ctx: dict[str, Any], settings: Settings, now: datetime
) -> int:
    maker = _sessionmaker(ctx)
    async with maker() as session:
        ids = await DeadlineService(session).due_action_deadline_ids(now)
    fired = 0
    for deadline_id in ids:
        try:
            if await _fire_one(ctx, deadline_id, now):
                fired += 1
        except Exception:  # noqa: BLE001 - one broken deadline must not abort the cycle
            logger.exception("deadline action failed (deadline=%s)", deadline_id)
    return fired


async def _fire_one(ctx: dict[str, Any], deadline_id: UUID, now: datetime) -> bool:
    maker = _sessionmaker(ctx)
    dispatcher = ctx.get("flow_dispatcher") or build_notify_dispatcher(ctx.get("redis"))
    async with maker() as session:
        svc = DeadlineService(session)
        deadline = await svc.lock_action_deadline(deadline_id, now)
        if deadline is None:
            return False  # another worker holds it, or it is already consumed
        application_id = deadline.application_id
        transition_id = transition_ref(deadline.action_on_pass)
        if application_id is None or transition_id is None:
            logger.warning(
                "deadline %s has action_on_pass without application/transition — skipped",
                deadline_id,
            )
            await svc.consume_action(deadline)  # do not scan it again
            return False
        flow = FlowService(session, dispatcher)
        fired = False
        # Stage the marker before the fire: `fire` commits it together with the state
        # change. No window stays open for a second worker to re-grab an already-fired
        # deadline, because the row lock releases with the commit.
        deadline.action_on_pass = None
        try:
            await flow.fire(
                application_id,
                transition_id,
                _system_principal(),
                note=f"deadline:{deadline.kind}",
                deadline_passed=True,
                manual=False,
            )
            fired = True
        except ConflictError as exc:
            # The guard failed, or a concurrent transition already changed the state.
            # The deadline stays consumed. Do not fire it again.
            logger.info("deadline %s transition not applied: %s", deadline_id, exc)
        except NotFoundError as exc:
            logger.warning("deadline %s references missing app/transition: %s", deadline_id, exc)
        # On the error paths `fire` does not commit, so persist the marker here.
        # After a successful `fire` this call is a no-op.
        await svc.consume_action(deadline)
    return fired


async def _process_auto_transitions(ctx: dict[str, Any]) -> int:
    """Fire the configured automatic transitions whose guard passes.

    The scan finds applications whose current state has an outgoing `automatic`
    transition. It fires the first match with `manual=False`. Optimistic locking in
    `flow.fire` keeps the step idempotent. Each application gets its own session.
    """
    maker = _sessionmaker(ctx)
    dispatcher = ctx.get("flow_dispatcher") or build_notify_dispatcher(ctx.get("redis"))
    async with maker() as session:
        auto_states = select(Transition.from_state_id).where(Transition.automatic)
        # Capped per tick, oldest first: a large cohort drains over several ticks
        # instead of stretching one tick past the cron cadence.
        ids = list(
            (
                await session.execute(
                    select(Application.id)
                    .where(
                        Application.current_state_id.is_not(None),
                        Application.current_state_id.in_(auto_states),
                    )
                    .order_by(Application.created_at)
                    .limit(DEFAULT_SCAN_LIMIT)
                )
            )
            .scalars()
            .all()
        )
    advanced = 0
    for application_id in ids:
        try:
            async with maker() as session:
                flow = FlowService(session, dispatcher)
                if await flow.auto_advance(application_id, _system_principal()) is not None:
                    advanced += 1
        except (ConflictError, NotFoundError) as exc:
            logger.info("auto-transition skipped (app=%s): %s", application_id, exc)
        except Exception:  # noqa: BLE001 - one broken application must not abort the cycle
            logger.exception("auto-transition failed (app=%s)", application_id)
    return advanced


async def _process_votes(ctx: dict[str, Any], now: datetime) -> int:
    maker = _sessionmaker(ctx)
    async with maker() as session:
        ids = await DeadlineService(session).due_open_vote_ids(now)
    closed = 0
    for vote_id in ids:
        try:
            if await _close_one(ctx, vote_id, now):
                closed += 1
        except Exception:  # noqa: BLE001 - one broken vote must not abort the cycle
            logger.exception("vote auto-close failed (vote=%s)", vote_id)
    return closed


async def _close_one(ctx: dict[str, Any], vote_id: UUID, now: datetime) -> bool:
    maker = _sessionmaker(ctx)
    dispatcher = ctx.get("flow_dispatcher") or build_notify_dispatcher(ctx.get("redis"))
    async with maker() as session:
        svc = DeadlineService(session)
        vote = await svc.lock_open_vote(vote_id, now)
        if vote is None:
            return False  # another worker holds it, or it is already closed
        voting = VotingService(session, dispatcher)
        try:
            # Pass `now` so a time-bound vote past its window with an unmet quorum
            # closes for good on the fail branch. Without it the cron re-grabs the
            # vote forever.
            closed = await voting.close(vote.id, _system_principal(), now=now)
        except ConflictError as exc:
            logger.info("vote %s auto-close skipped: %s", vote_id, exc)
            return False
        except NotFoundError as exc:
            logger.warning("vote %s auto-close — app missing: %s", vote_id, exc)
            return False
    logger.info("vote auto-closed (vote=%s)", vote_id)
    # Replay the `vote_closed` broadcast that the REST router normally sends. Without
    # it the beamer and the voters show the time-closed vote as open until a reload.
    # This runs after the commit and is best effort: a broker fault must not fail the
    # already-closed vote. It is a no-op for standalone votes (`meeting_id is None`).
    await _broadcast_vote_closed(ctx, closed)
    return True


async def _broadcast_vote_closed(ctx: dict[str, Any], closed: VoteClosed) -> None:
    """Fan out `vote_closed` over the Redis broker (best effort)."""
    redis = ctx.get("redis")
    if redis is None:
        return
    try:
        await BrokerPublisher(RedisBroker(redis)).vote_closed(closed)
    except Exception as exc:  # noqa: BLE001 - broadcast is not close-critical
        logger.warning("vote_closed broadcast failed (vote=%s): %s", closed.id, exc)
