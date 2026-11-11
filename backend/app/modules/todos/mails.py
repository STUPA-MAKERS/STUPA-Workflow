"""To-do mails: ``todo_assigned``, ``todo_mentioned`` and ``todo_due``.

``todo_assigned`` goes to a newly added assignee other than the actor,
``todo_mentioned`` to the newly mentioned members other than the author. The router
sends both after the commit as a background task with its own session, and both are
best effort: a mail failure never fails the write. ``todo_due`` reminds the
assignees of an open card the day before it is due; the deadline cron sends it
(``worker/todos.py``). Each kind is in ``NOTIFICATION_KINDS``, so a person can
switch it off. The link opens the card on its board.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.notifications.links import todo_link
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.notifications.texts.todos import (
    TODO_ASSIGNED_BODY,
    TODO_ASSIGNED_KEY,
    TODO_ASSIGNED_SUBJECT,
    TODO_DUE_BODY,
    TODO_DUE_KEY,
    TODO_DUE_SUBJECT,
    TODO_MENTIONED_BODY,
    TODO_MENTIONED_KEY,
    TODO_MENTIONED_SUBJECT,
)
from app.modules.todos.models import TodoBoard, TodoCard
from app.modules.todos.service import TodoMail
from app.settings import Settings

logger = logging.getLogger("app.todos")


def _maker(
    sessionmaker: async_sessionmaker[AsyncSession] | None,
) -> async_sessionmaker[AsyncSession]:
    return sessionmaker if sessionmaker is not None else get_sessionmaker()


async def _addresses(session: AsyncSession, ids: Sequence[UUID]) -> list[str]:
    if not ids:
        return []
    rows = (
        await session.scalars(
            select(PrincipalRow.email).where(
                PrincipalRow.id.in_(list(ids)),
                PrincipalRow.active.is_(True),
                PrincipalRow.email.is_not(None),
            )
        )
    ).all()
    return sorted({str(email) for email in rows if email})


async def _name(session: AsyncSession, principal_id: UUID) -> str:
    row = await session.get(PrincipalRow, principal_id)
    if row is None:
        return ""
    return row.display_name or row.email or ""


async def send_todo_mail(
    session: AsyncSession, *, queue: MailQueue | None, settings: Settings, mail: TodoMail
) -> bool:
    """Send one ``todo_assigned`` or ``todo_mentioned`` mail of the outbox.

    Returns:
        True when a mail was enqueued.
    """
    card = await session.get(TodoCard, mail.card_id)
    board = await session.get(TodoBoard, card.board_id) if card is not None else None
    if card is None or board is None:
        return False
    recipients = await _addresses(session, mail.recipients)
    if not recipients:
        return False
    assigned = mail.kind == "assigned"
    key = TODO_ASSIGNED_KEY if assigned else TODO_MENTIONED_KEY
    excerpt: dict[str, object] = {} if assigned else {"excerpt": mail.excerpt or ""}
    context: dict[str, object] = {
        "cardTitle": card.title,
        "boardName": board.name,
        "actor": await _name(session, mail.actor_id),
        **excerpt,
    }
    return await NotificationService(session, queue=queue, settings=settings).send_kind_mail(
        recipients,
        kind=key,
        template_key=key,
        builtin_subject=TODO_ASSIGNED_SUBJECT if assigned else TODO_MENTIONED_SUBJECT,
        builtin_body=TODO_ASSIGNED_BODY if assigned else TODO_MENTIONED_BODY,
        context=context,
        idempotency_parts=(
            key,
            str(card.id),
            ",".join(sorted(str(r) for r in mail.recipients)),
            str(mail.event_id),
        ),
        link=todo_link(settings, card.id),
    )


async def notify_todo_mails(
    *,
    queue: MailQueue | None,
    settings: Settings,
    mails: Sequence[TodoMail],
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Send the outbox of a request (best effort).

    Returns:
        The number of enqueued mails.
    """

    async def send_one(mail: TodoMail) -> bool:
        try:
            async with _maker(sessionmaker)() as session:
                return await send_todo_mail(session, queue=queue, settings=settings, mail=mail)
        except Exception:
            logger.exception("%s mail failed", mail.kind)
            return False

    sent = [await send_one(mail) for mail in mails]
    return sum(sent)


async def send_todo_due(
    session: AsyncSession,
    *,
    queue: MailQueue | None,
    settings: Settings,
    card: TodoCard,
    board: TodoBoard,
    assignee_ids: Sequence[UUID],
    due: date,
) -> bool:
    """Remind the assignees of a card that it is due tomorrow (one mail per due date).

    Returns:
        True when a mail was enqueued.
    """
    recipients = await _addresses(session, assignee_ids)
    if not recipients:
        return False
    return await NotificationService(session, queue=queue, settings=settings).send_kind_mail(
        recipients,
        kind=TODO_DUE_KEY,
        template_key=TODO_DUE_KEY,
        builtin_subject=TODO_DUE_SUBJECT,
        builtin_body=TODO_DUE_BODY,
        context={"cardTitle": card.title, "boardName": board.name, "dueDate": due.isoformat()},
        idempotency_parts=(TODO_DUE_KEY, str(card.id), due.isoformat()),
        link=todo_link(settings, card.id),
    )
