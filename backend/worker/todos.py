"""arq tasks of the to-do boards: the archive cron and the due reminder.

``archive_done_todos`` runs once a day at 03:50. A card is due when it is in the
done column of its board, not archived, and its ``completed_at`` is older than the
``archive_after_days`` of the board. A board with ``archive_after_days`` null never
archives. Each archived card gets the event ``archived`` without an actor (the
system), and the board gets a new ``updated_at``, so its ETag changes. The cron
locks the boards of the due cards first (ordered by id), then the cards, because a
move locks the board and then updates the card, and the other order deadlocks.

``process_todo_due`` runs inside the deadline cron (``worker/deadlines.py``), so every
minute. From 07:00 Europe/Berlin on, it reminds the assignees of every open card
(not archived, not in a done column) that is due tomorrow (Europe/Berlin) with the
mail ``todo_due``. An assignee who is no longer a member of the board (an ended
gremium membership, a lost team permission) gets no reminder, because the mail
carries the card title and the board name that the person can no longer read; the
row in ``todo_assignee`` stays. ``todo_card.due_reminded_on`` keeps the due date of the last
reminder, so a card gets one reminder per due date, also after the arq job id of
the mail expires. A new due date gets a new reminder.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.notifications.queue import ArqMailQueue, MailQueue
from app.modules.notifications.todos import send_todo_due
from app.modules.todos.access import BoardAccess
from app.modules.todos.models import (
    TodoAssignee,
    TodoBoard,
    TodoCard,
    TodoColumn,
    TodoEvent,
)
from app.modules.todos.service import BERLIN
from app.settings import Settings, load_settings

logger = logging.getLogger("worker.todos")

#: The Berlin hour from which the due reminder goes out.
DUE_HOUR = 7
#: The most cards that one run handles.
BATCH = 500


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via ``ctx['todos_sessionmaker']``)."""
    maker = ctx.get("todos_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _mail_queue(ctx: dict[str, Any]) -> MailQueue | None:
    queue: MailQueue | None = ctx.get("mail_queue")
    if queue is not None:
        return queue
    pool = ctx.get("redis")
    return ArqMailQueue(pool) if pool is not None else None


async def archive_done_todos(ctx: dict[str, Any], now: datetime | None = None) -> int:
    """Archive the cards that stay in the done column past the board's limit.

    Returns:
        The number of archived cards.
    """
    moment = now or datetime.now(UTC)
    cutoff = moment - func.make_interval(0, 0, 0, TodoBoard.archive_after_days)
    due = (
        TodoColumn.is_done.is_(True),
        TodoCard.archived_at.is_(None),
        TodoCard.completed_at.is_not(None),
        TodoBoard.archive_after_days.is_not(None),
        TodoCard.completed_at < cutoff,
    )
    async with _sessionmaker(ctx)() as session:
        candidates = (
            select(TodoCard.board_id)
            .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
            .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
            .where(*due)
            .order_by(TodoCard.completed_at, TodoCard.id)
            .limit(BATCH)
            .subquery()
        )
        boards = (
            await session.scalars(
                select(TodoBoard.id)
                .where(TodoBoard.id.in_(select(candidates.c.board_id)))
                .order_by(TodoBoard.id)
                .with_for_update()
            )
        ).all()
        rows = (
            (
                await session.execute(
                    select(TodoCard, TodoBoard)
                    .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                    .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                    .where(*due, TodoCard.board_id.in_(boards))
                    .order_by(TodoCard.completed_at, TodoCard.id)
                    .limit(BATCH)
                    .with_for_update(of=TodoCard, skip_locked=True)
                )
            ).all()
            if boards
            else []
        )
        for card, board in rows:
            card.archived_at = moment
            board.updated_at = moment
            session.add(
                TodoEvent(
                    id=uuid.uuid4(),
                    card_id=card.id,
                    actor_id=None,
                    kind="archived",
                    payload={},
                    created_at=moment,
                )
            )
        if rows:
            await session.commit()
            logger.info("archived %d to-do card(s)", len(rows))
    return len(rows)


async def process_todo_due(ctx: dict[str, Any], now: datetime | None = None) -> int:
    """Send the ``todo_due`` reminder for the open cards due tomorrow.

    Returns:
        The number of reminded cards.

    One bad card is logged and does not stop the run.
    """
    local = (now or datetime.now(UTC)).astimezone(BERLIN)
    if local.hour < DUE_HOUR:
        return 0
    tomorrow = local.date() + timedelta(days=1)
    settings: Settings = ctx.get("settings") or load_settings()
    queue = _mail_queue(ctx)
    sent = 0
    async with _sessionmaker(ctx)() as session:
        access = BoardAccess(session)
        members: dict[uuid.UUID, set[uuid.UUID]] = {}
        rows = (
            await session.execute(
                select(TodoCard, TodoBoard)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                .where(
                    TodoCard.due_date == tomorrow,
                    TodoCard.archived_at.is_(None),
                    TodoColumn.is_done.is_(False),
                    TodoCard.due_reminded_on.is_distinct_from(tomorrow),
                )
                .order_by(TodoCard.id)
                .limit(BATCH)
                .with_for_update(of=TodoCard, skip_locked=True)
            )
        ).all()
        for card, board in rows:
            if board.id not in members:
                members[board.id] = await access.member_ids(board)
            assignees = [
                pid
                for pid in (
                    await session.scalars(
                        select(TodoAssignee.principal_id).where(TodoAssignee.card_id == card.id)
                    )
                ).all()
                if pid in members[board.id]
            ]
            try:
                if await send_todo_due(
                    session,
                    queue=queue,
                    settings=settings,
                    card=card,
                    board=board,
                    assignee_ids=assignees,
                    due=tomorrow,
                ):
                    sent += 1
            except Exception:
                logger.exception("todo_due mail failed for %s", card.id)
                continue
            card.due_reminded_on = tomorrow
        if rows:
            await session.commit()
    return sent
