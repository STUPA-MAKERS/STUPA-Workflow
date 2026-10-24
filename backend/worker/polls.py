"""arq step of the polls: the reminder mail 24 h before the end.

``process_poll_reminders`` runs inside the deadline cron (``worker/deadlines.py``), so
every minute. A poll of a Gremium (``kind = 'poll'``, no meeting) is due when it is
open, has no reminder yet (``reminded_at`` NULL), ends within the next 24 h, and runs
at least 24 h from its open to its end. A shorter poll gets no reminder. The step
sends ``poll_reminder`` to the eligible members without an answer and sets
``reminded_at``, also when nobody is left to remind, so the poll gets one reminder.
The close at the end is the vote close of the same cron (``_process_votes``).

The rows are locked with ``FOR UPDATE SKIP LOCKED``, so a second worker skips them.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.notifications.polls import send_poll_mail
from app.modules.notifications.queue import ArqMailQueue, MailQueue
from app.modules.voting.models import Vote
from app.settings import Settings, load_settings

logger = logging.getLogger("worker.polls")

#: The reminder goes out this long before the end of a poll.
REMINDER_LEAD = timedelta(hours=24)
#: The most polls that one run handles.
BATCH = 200


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via ``ctx['polls_sessionmaker']``)."""
    maker = ctx.get("polls_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _mail_queue(ctx: dict[str, Any]) -> MailQueue | None:
    queue: MailQueue | None = ctx.get("mail_queue")
    if queue is not None:
        return queue
    pool = ctx.get("redis")
    return ArqMailQueue(pool) if pool is not None else None


async def process_poll_reminders(ctx: dict[str, Any], now: datetime | None = None) -> int:
    """Send the ``poll_reminder`` of the polls that end within 24 h.

    Returns:
        The number of polls with an enqueued reminder.
    """
    moment = now or datetime.now(UTC)
    settings: Settings = ctx.get("settings") or load_settings()
    queue = _mail_queue(ctx)
    sent = 0
    async with _sessionmaker(ctx)() as session:
        rows = (
            await session.scalars(
                select(Vote)
                .where(
                    Vote.kind == "poll",
                    Vote.meeting_id.is_(None),
                    Vote.status == "open",
                    Vote.reminded_at.is_(None),
                    Vote.closes_at.is_not(None),
                    Vote.closes_at > moment,
                    Vote.closes_at <= moment + REMINDER_LEAD,
                    Vote.opens_at.is_not(None),
                    Vote.closes_at - Vote.opens_at >= REMINDER_LEAD,
                )
                .order_by(Vote.closes_at, Vote.id)
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for vote in rows:
            try:
                if await send_poll_mail(
                    session,
                    queue=queue,
                    settings=settings,
                    vote=vote,
                    now=moment,
                    reminder=True,
                ):
                    sent += 1
            except Exception:  # noqa: BLE001 - one bad poll must not stop the run
                logger.exception("poll_reminder mail failed for %s", vote.id)
                continue
            vote.reminded_at = moment
        if rows:
            await session.commit()
    return sent
