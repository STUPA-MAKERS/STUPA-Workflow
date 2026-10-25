"""arq cron task: scheduled vote, flow and reminder processing.

`process_deadlines` runs every minute against a tz-aware `now` in UTC. It runs these
idempotent steps:

1. Vote auto-close. An open vote past `closes_at` goes to `voting.close`, which
   tallies the vote and fires the result branch. The close always ends the vote, also
   when the branch is blocked (`branchFired=false`, audit `vote_branch_blocked`), so
   the cron never grabs the same vote again.
2. Auto-transitions. A confirmed application in a state with an `automatic`
   transition fires it when the guard passes.
3. Discard. An application whose email stays unconfirmed longer than
   `guest_application_settings.confirm_ttl_hours` is deleted, with its MinIO
   objects and a `guest_application_discard` audit entry without PII.
4. To-do reminders. `process_todo_due` (`worker/todos.py`) sends `todo_due` for the
   open cards due tomorrow. A failure of this step is logged and does not stop the
   cycle.
5. Poll reminders. `process_poll_reminders` (`worker/polls.py`) sends `poll_reminder`
   24 h before the end of a poll of a Gremium. A failure of this step is logged and
   does not stop the cycle.

An unconfirmed guest application (`email_confirmed_at IS NULL`) rests in the flow. The
auto-transition scan skips it. The magic-link verify starts its flow
(`FlowService.start_confirmed`).

Concurrency: each unit gets a lock in its own session with `FOR UPDATE SKIP LOCKED`.
A second worker skips a locked unit, so nothing runs twice. The operations are also
idempotent by themselves: `flow.fire` uses optimistic locking, `voting.close` checks
the status, and the mail enqueue deduplicates on `_job_id`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.applications.guest_settings import load_guest_settings
from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.files.models import Attachment
from app.modules.files.storage import ObjectStorage, StorageError, build_object_storage
from app.modules.flow.dispatch import ActionDispatcher, build_worker_dispatcher
from app.modules.flow.models import Transition
from app.modules.flow.service import FlowService
from app.modules.livevote.broker import RedisBroker
from app.modules.livevote.service import BrokerPublisher
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteClosed
from app.modules.voting.service import VotingService
from app.settings import Settings, load_settings
from app.shared.errors import ConflictError, NotFoundError
from worker.polls import process_poll_reminders
from worker.todos import process_todo_due

logger = logging.getLogger("app.deadlines")

#: Audit actor of the discard of unconfirmed applications.
_DISCARD_ACTOR = "system:deadlines"

#: Cap per cron tick and step, oldest row first. A large backlog drains over several
#: ticks, so one tick does not overrun the 1-minute cadence. Correctness does not
#: change, because SKIP LOCKED and the status checks protect the run, and a row that no
#: worker takes stays due for the next tick.
DEFAULT_SCAN_LIMIT = 200


async def on_startup(ctx: dict[str, Any]) -> None:
    """Load the settings into the worker context."""
    ctx["settings"] = load_settings()


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via `ctx['deadlines_sessionmaker']`)."""
    maker = ctx.get("deadlines_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _flow_dispatcher(ctx: dict[str, Any]) -> ActionDispatcher:
    """Return the flow action dispatcher of the worker.

    `worker.main` sets `ctx['flow_dispatcher']` on startup. Without it the worker
    builds the same full chain (notify, webhook, extras) over the arq pool. A cron
    transition therefore runs every configured action, not only the mails.
    """
    dispatcher = ctx.get("flow_dispatcher")
    if dispatcher is not None:
        return dispatcher
    return build_worker_dispatcher(
        ctx.get("redis"), _sessionmaker(ctx), ctx.get("settings")
    )


def _publisher(ctx: dict[str, Any]) -> BrokerPublisher | None:
    """Return the live-vote publisher over the arq Redis pool, or `None` without Redis.

    A transition that leaves a vote state cancels its votes. The publisher sends
    `vote_cancelled` to the live clients of the meeting.
    """
    redis = ctx.get("redis")
    return BrokerPublisher(RedisBroker(redis)) if redis is not None else None


def _now() -> datetime:
    """Return the current tz-aware UTC time (tests control it with freezegun)."""
    return datetime.now(UTC)


def _system_principal() -> Principal:
    """Build the actor for cron-triggered transitions.

    No user stands behind this principal. `application.manage` covers the role guards
    on the automatic transitions and the result branches.
    """
    return Principal(
        sub="system:deadlines",
        roles=["system"],
        permissions={"application.manage"},
    )


async def process_deadlines(ctx: dict[str, Any]) -> str:
    """Run vote auto-close, auto-transitions, discard and reminders (idempotent)."""
    settings: Settings = ctx.get("settings") or load_settings()
    now = _now()
    closed = await _process_votes(ctx, now)
    advanced = await _process_auto_transitions(ctx)
    discarded = await _discard_unconfirmed(ctx, now, settings)
    todos = await _process_todo_due(ctx, now)
    polls = await _process_poll_reminders(ctx, now)
    return (
        f"votes={closed} "
        f"auto={advanced} discarded={discarded} todos={todos} polls={polls}"
    )


async def _process_poll_reminders(ctx: dict[str, Any], now: datetime) -> int:
    """Run the poll reminder; a failure costs only this step."""
    try:
        return await process_poll_reminders(ctx, now)
    except Exception:
        logger.exception("poll reminders failed")
        return 0


async def _process_todo_due(ctx: dict[str, Any], now: datetime) -> int:
    """Run the to-do due reminder; a failure costs only this step."""
    try:
        return await process_todo_due(ctx, now)
    except Exception:
        logger.exception("todo_due reminders failed")
        return 0


async def _discard_unconfirmed(
    ctx: dict[str, Any], now: datetime, settings: Settings | None = None
) -> int:
    """Delete the applications that stay unconfirmed past the confirmation window.

    The window is `guest_application_settings.confirm_ttl_hours`. The step reads it
    on every run, so a changed value applies to the waiting applications too.
    The step covers every application with `email_confirmed_at IS NULL`, also one
    that a logged-in person submitted for another email address.

    The order is fixed. The step locks the due rows (`FOR UPDATE SKIP LOCKED`) and
    reads their attachment storage keys. It deletes the rows (the dependent rows
    cascade) and writes one `guest_application_discard` audit entry per
    application, without PII. After the commit it removes the MinIO objects as best
    effort. A second run finds nothing.
    """
    maker = _sessionmaker(ctx)
    async with maker() as session:
        ttl_hours = (await load_guest_settings(session)).confirm_ttl_hours
        cutoff = now - timedelta(hours=ttl_hours)
        due = (
            await session.execute(
                select(Application.id, Application.type_id, Application.gremium_id)
                .where(
                    Application.email_confirmed_at.is_(None),
                    Application.created_at < cutoff,
                )
                .order_by(Application.created_at)
                .limit(DEFAULT_SCAN_LIMIT)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not due:
            return 0
        ids = [row.id for row in due]
        attachments = (
            await session.execute(
                select(Attachment.application_id, Attachment.storage_key).where(
                    Attachment.application_id.is_not(None),
                    Attachment.application_id.in_(ids),
                )
            )
        ).all()
        await session.execute(delete(Application).where(Application.id.in_(ids)))
        for row in due:
            await audit_record(
                session,
                actor=_DISCARD_ACTOR,
                action=AuditAction.GUEST_APPLICATION_DISCARD,
                target_type="application",
                target_id=str(row.id),
                data={
                    "typeId": str(row.type_id),
                    "gremiumId": str(row.gremium_id) if row.gremium_id else None,
                    "attachments": sum(
                        1 for a in attachments if a.application_id == row.id
                    ),
                    "confirmTtlHours": ttl_hours,
                },
            )
        await session.commit()
    keys = [a.storage_key for a in attachments if a.storage_key is not None]
    await _remove_objects(ctx, settings, keys)
    logger.info("discarded %d unconfirmed guest application(s)", len(ids))
    return len(ids)


async def _remove_objects(
    ctx: dict[str, Any], settings: Settings | None, keys: list[str]
) -> None:
    """Remove the storage objects of discarded attachments (best effort).

    The rows are already gone. A failed removal leaves an orphan object and a
    warning in the log, but it does not undo the discard.
    """
    if not keys:
        return
    storage: ObjectStorage | None = ctx.get("object_storage")
    if storage is None and settings is not None:
        storage = build_object_storage(settings)
    if storage is None:
        logger.warning(
            "no object storage: %d object(s) of discarded applications stay", len(keys)
        )
        return
    for key in keys:
        try:
            await storage.remove(key)
        except StorageError:
            logger.warning("could not remove an object of a discarded application")


async def _process_auto_transitions(ctx: dict[str, Any]) -> int:
    """Fire the configured automatic transitions whose guard passes.

    The scan finds confirmed applications whose current state has an outgoing
    `automatic` transition. It fires the first match with `manual=False`. Optimistic
    locking in `flow.fire` keeps the step idempotent. Each application gets its own
    session.

    The scan is capped per tick, oldest first, so a large cohort drains over several ticks
    instead of stretching one tick past the cron cadence. One broken application is logged
    and does not abort the cycle.
    """
    maker = _sessionmaker(ctx)
    dispatcher = _flow_dispatcher(ctx)
    async with maker() as session:
        auto_states = select(Transition.from_state_id).where(Transition.automatic)
        ids = list(
            (
                await session.execute(
                    select(Application.id)
                    .where(
                        Application.current_state_id.is_not(None),
                        Application.current_state_id.in_(auto_states),
                        Application.email_confirmed_at.is_not(None),
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
                flow = FlowService(session, dispatcher, _publisher(ctx))
                if await flow.auto_advance(application_id, _system_principal()) is not None:
                    advanced += 1
        except (ConflictError, NotFoundError) as exc:
            logger.info("auto-transition skipped (app=%s): %s", application_id, exc)
        except Exception:
            logger.exception("auto-transition failed (app=%s)", application_id)
    return advanced


async def due_open_vote_ids(
    session: AsyncSession, now: datetime, *, limit: int = DEFAULT_SCAN_LIMIT
) -> list[UUID]:
    """List the ids of open votes whose window has passed, oldest first, up to `limit`."""
    rows = (
        await session.execute(
            select(Vote.id)
            .where(
                Vote.status == "open",
                Vote.closes_at.isnot(None),
                Vote.closes_at <= now,
            )
            .order_by(Vote.closes_at)
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def lock_open_vote(
    session: AsyncSession, vote_id: UUID, now: datetime
) -> Vote | None:
    """Lock an open vote that has expired, with `SKIP LOCKED`.

    Returns:
        The locked vote. It returns `None` when another worker holds the row, or
        when the vote is closed already.
    """
    return (
        await session.execute(
            select(Vote)
            .where(
                Vote.id == vote_id,
                Vote.status == "open",
                Vote.closes_at.isnot(None),
                Vote.closes_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()


async def _process_votes(ctx: dict[str, Any], now: datetime) -> int:
    """Close the open votes whose time window ended; return how many closed.

    One broken vote is logged and does not abort the cycle.
    """
    maker = _sessionmaker(ctx)
    async with maker() as session:
        ids = await due_open_vote_ids(session, now)
    closed = 0
    for vote_id in ids:
        try:
            if await _close_one(ctx, vote_id, now):
                closed += 1
        except Exception:
            logger.exception("vote auto-close failed (vote=%s)", vote_id)
    return closed


async def _close_one(ctx: dict[str, Any], vote_id: UUID, now: datetime) -> bool:
    """Close one due vote and fire its result branch; return whether it closed.

    A vote that another worker holds or that is already closed gives False. ``now`` is
    passed on, so a time-bound vote past its window with an unmet quorum closes for good on
    the fail branch; without it the cron re-grabs the vote forever. When the result branch
    is blocked, the vote stays closed, the audit log holds ``vote_branch_blocked``, a person
    moves the application by hand, and the cron does not retry.

    After the commit the function replays the ``vote_closed`` broadcast that the REST router
    normally sends, because the beamer and the voters would show the vote as open until a
    reload. The broadcast is best effort, so a broker fault does not fail the closed vote,
    and it is a no-op for a standalone vote.
    """
    maker = _sessionmaker(ctx)
    dispatcher = _flow_dispatcher(ctx)
    async with maker() as session:
        vote = await lock_open_vote(session, vote_id, now)
        if vote is None:
            return False
        voting = VotingService(session, dispatcher)
        try:
            closed = await voting.close(vote.id, _system_principal(), now=now)
        except ConflictError as exc:
            logger.info("vote %s auto-close skipped: %s", vote_id, exc)
            return False
    if closed.application_id is not None and not closed.branch_fired:
        logger.warning("vote auto-closed, result branch blocked (vote=%s)", vote_id)
    else:
        logger.info("vote auto-closed (vote=%s)", vote_id)
    await _broadcast_vote_closed(ctx, closed)
    return True


async def _broadcast_vote_closed(ctx: dict[str, Any], closed: VoteClosed) -> None:
    """Fan out `vote_closed` over the Redis broker (best effort)."""
    redis = ctx.get("redis")
    if redis is None:
        return
    try:
        await BrokerPublisher(RedisBroker(redis)).vote_closed(closed)
    except Exception as exc:
        logger.warning("vote_closed broadcast failed (vote=%s): %s", closed.id, exc)
