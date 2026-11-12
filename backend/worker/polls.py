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
from app.modules.notifications.queue import ArqMailQueue, MailQueue
from app.modules.site_config.features import Feature
from app.modules.voting.models import Vote
from app.modules.voting.poll_mails import send_poll_mail
from app.settings import Settings, load_settings
from worker.features import job_feature_on

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

    One bad poll is logged and does not stop the run. No mail goes out while
    `Abstimmungen` is off.
    """
    if not await job_feature_on(_sessionmaker(ctx), Feature.VOTING):
        return 0
    moment = now or datetime.now(UTC)
    settings: Settings = ctx.get("settings") or load_settings()
    queue = _mail_queue(ctx)
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
        sent = sum(
            [await _remind(session, queue, settings, vote, moment) for vote in rows]
        )
        if rows:
            await session.commit()
    return sent


async def _remind(
    session: AsyncSession,
    queue: MailQueue | None,
    settings: Settings,
    vote: Vote,
    moment: datetime,
) -> bool:
    """Send the reminder of one poll and mark it as reminded.

    Returns:
        Whether a mail went out. A failed send logs and leaves the poll unmarked, so the
        next run tries it again.
    """
    try:
        sent = await send_poll_mail(
            session, queue=queue, settings=settings, vote=vote, reminder=True
        )
    except Exception:
        logger.exception("poll_reminder mail failed for %s", vote.id)
        return False
    vote.reminded_at = moment
    return sent
