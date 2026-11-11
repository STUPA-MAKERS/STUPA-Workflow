"""Mention mail ``ticket_mentioned``.

A person whom a chat message newly mentions gets one mail: ``comment_mentioned`` for a
comment on an application (`app.modules.applications.mention_mails`),
``ticket_mentioned`` for a note on a ticket (`app.modules.tickets.mention_mails`).
"Newly" means the mentions that the write added (all of them at the create, at an edit only the ids
that the stored list did not hold), so an edit never mails a person twice. The actor
(the person who wrote the mention) never gets the mail.

Both run as background tasks after the commit, each with its own session, and both
are best effort: a mail failure never fails the write. The kind is ``mention``, so
each person can switch the mails off.

Each recipient gets an own mail with the idempotency key (key, message id, recipient).
The key is the arq job id, so an edit that removes a mention and then adds it again
sends no second mail while the queue still holds the first job.

A mentioned person is a member (a reader of the internal comments, or a holder of
``ticket.manage``), so the mail names the actor and the author with their display
names, and an internal comment mails like a public one. Only an active account with
an address that the message still mentions gets the mail. The mail uses the default
language of the platform, like every mail to the team. The excerpt is the text of the
message (``comment_mail_text``: the file names without a text), cut at the length of
the comment mails. The HTML body shows it as the chat bubble of the comment mails.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.files.service import FilesService
from app.modules.notifications.chat_mail import (
    addresses,
    comment_mail_text,
    display_name,
    initials,
    maker,
    send_each,
)
from app.modules.notifications.links import ticket_link
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.texts.comments import (
    COMMENT_EXCERPT_LEN,
)
from app.modules.notifications.texts.mentions import (
    TICKET_MENTIONED_BODY,
    TICKET_MENTIONED_HTML,
    TICKET_MENTIONED_KEY,
    TICKET_MENTIONED_SUBJECT,
)
from app.modules.tickets.models import Ticket, TicketNote
from app.modules.tickets.service import format_number
from app.settings import Settings
from app.shared.mentions import mention_ids

logger = logging.getLogger("app.notifications")


async def _note_filenames(session: AsyncSession, note: TicketNote) -> list[str]:
    """Return the file names of the attachments of a ticket note."""
    files = await FilesService(session).message_attachments("ticket_note", [note.id])
    return [a.filename for a in files.get(note.id, [])]


async def send_ticket_mentions(
    session: AsyncSession,
    *,
    queue: MailQueue | None,
    settings: Settings,
    note_id: UUID,
    recipients: Sequence[UUID],
) -> int:
    """Mail the newly mentioned holders of ``ticket.manage`` of a ticket note.

    The author of the note is the actor: only the author writes or edits a note.

    Returns:
        The number of enqueued mails.
    """
    note = await session.get(TicketNote, note_id)
    if note is None or note.deleted_at is not None or not recipients:
        return 0
    ticket = await session.get(Ticket, note.ticket_id)
    if ticket is None:
        return 0
    still = set(mention_ids(note.mentions))
    targets = await addresses(
        session, [pid for pid in recipients if pid in still], skip=note.author_id
    )
    if not targets:
        return 0
    author = display_name(
        await session.get(PrincipalRow, note.author_id) if note.author_id else None
    )
    filenames = await _note_filenames(session, note) if not note.body.strip() else []
    message = comment_mail_text(note.body, filenames)
    context: dict[str, object] = {
        "actor": author,
        "number": format_number(ticket.number),
        "title": ticket.title,
        "message": message[:COMMENT_EXCERPT_LEN],
        "author": author,
        "authorInitials": initials(author),
    }
    return await send_each(
        session,
        queue=queue,
        settings=settings,
        recipients=targets,
        key=TICKET_MENTIONED_KEY,
        subject=TICKET_MENTIONED_SUBJECT,
        body=TICKET_MENTIONED_BODY,
        html=TICKET_MENTIONED_HTML,
        context=context,
        message_id=note.id,
        link=ticket_link(settings, ticket.id, note_id=note.id),
    )


async def notify_ticket_mentions(
    *,
    queue: MailQueue | None,
    settings: Settings,
    note_id: UUID,
    recipients: Sequence[UUID],
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Run `send_ticket_mentions` in an own session (best effort).

    Returns:
        The number of enqueued mails, 0 after a failure.
    """
    try:
        async with maker(sessionmaker)() as session:
            return await send_ticket_mentions(
                session, queue=queue, settings=settings, note_id=note_id, recipients=recipients
            )
    except Exception:
        logger.exception("ticket_mentioned mail failed")
        return 0
