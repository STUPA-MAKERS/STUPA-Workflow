"""Mention mails: ``comment_mentioned`` and ``ticket_mentioned``.

A person whom a chat message newly mentions gets one mail: ``comment_mentioned`` for a
comment on an application, ``ticket_mentioned`` for a note on a ticket. "Newly" means
the mentions that the write added (all of them at the create, at an edit only the ids
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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.applications.models import Application, Comment
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.files.service import FilesService
from app.modules.notifications.comments import (
    _APPLICANT_AUTHOR_FALLBACK,
    _CHAT_BUBBLE_HTML,
    _COMMENT_EXCERPT_LEN,
    _initials,
    comment_mail_text,
)
from app.modules.notifications.links import MailLink, application_link, ticket_link
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.tickets.models import Ticket, TicketNote
from app.modules.tickets.service import format_number
from app.settings import Settings
from app.shared.i18n import pick_lang
from app.shared.mentions import mention_ids

logger = logging.getLogger("app.notifications")

#: The opt-out kind of both mention mails.
MENTION_KIND = "mention"
COMMENT_MENTIONED_KEY = "comment_mentioned"
TICKET_MENTIONED_KEY = "ticket_mentioned"

COMMENT_MENTIONED_SUBJECT: dict[str, str] = {
    "de": "{{ actor }} hat Sie erwähnt: {{ applicationTitle }}",
    "en": "{{ actor }} mentioned you: {{ applicationTitle }}",
}
COMMENT_MENTIONED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ actor }} hat Sie in einem Kommentar zum Antrag "
    "„{{ applicationTitle }}“ erwähnt:\n\n{{ comment }}\n",
    "en": "Hello,\n\n{{ actor }} mentioned you in a comment on the application "
    '"{{ applicationTitle }}":\n\n{{ comment }}\n',
}
COMMENT_MENTIONED_HTML: dict[str, str] = {
    "de": '<p style="margin:0 0 1em;">Hallo,</p>'
    '<p style="margin:0;">{{ actor }} hat Sie in einem Kommentar zum Antrag '
    "„{{ applicationTitle }}“ erwähnt:</p>" + _CHAT_BUBBLE_HTML,
    "en": '<p style="margin:0 0 1em;">Hello,</p>'
    '<p style="margin:0;">{{ actor }} mentioned you in a comment on the application '
    '"{{ applicationTitle }}":</p>' + _CHAT_BUBBLE_HTML,
}
COMMENT_MENTIONED_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Kommentar (ohne den Platzhalter hängt die Mail ihn an)",
    "actor": "Name der Person, die erwähnt hat",
    "applicationTitle": "Titel des Antrags",
    "applicationId": "ID des Antrags",
    "comment": "Kommentartext (Auszug; ohne Text die Namen der Dateien)",
    "commentAuthor": "Name der Kommentar-Autor:in",
    "commentAuthorInitials": "Initialen der Kommentar-Autor:in",
}

#: Chat bubble of the comment mails, with the placeholder names of the ticket context.
_NOTE_BUBBLE_HTML = (
    _CHAT_BUBBLE_HTML.replace("{{ commentAuthorInitials }}", "{{ authorInitials }}")
    .replace("{{ commentAuthor }}", "{{ author }}")
    .replace("{{ comment |", "{{ message |")
)

TICKET_MENTIONED_SUBJECT: dict[str, str] = {
    "de": "{{ actor }} hat Sie erwähnt: {{ number }} · {{ title }}",
    "en": "{{ actor }} mentioned you: {{ number }} · {{ title }}",
}
TICKET_MENTIONED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ actor }} hat Sie in einer Notiz zum Ticket {{ number }} "
    "„{{ title }}“ erwähnt:\n\n{{ message }}\n",
    "en": "Hello,\n\n{{ actor }} mentioned you in a note on the ticket {{ number }} "
    '"{{ title }}":\n\n{{ message }}\n',
}
TICKET_MENTIONED_HTML: dict[str, str] = {
    "de": '<p style="margin:0 0 1em;">Hallo,</p>'
    '<p style="margin:0;">{{ actor }} hat Sie in einer Notiz zum Ticket {{ number }} '
    "„{{ title }}“ erwähnt:</p>" + _NOTE_BUBBLE_HTML,
    "en": '<p style="margin:0 0 1em;">Hello,</p>'
    '<p style="margin:0;">{{ actor }} mentioned you in a note on the ticket {{ number }} '
    '"{{ title }}":</p>' + _NOTE_BUBBLE_HTML,
}
TICKET_MENTIONED_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zur Notiz (ohne den Platzhalter hängt die Mail ihn an)",
    "actor": "Name der Person, die erwähnt hat",
    "number": "Ticketnummer (T-0042)",
    "title": "Titel des Tickets",
    "message": "Text der Notiz (Auszug; ohne Text die Namen der Dateien)",
    "author": "Name der Autor:in der Notiz",
    "authorInitials": "Initialen der Autor:in der Notiz",
}


def _maker(
    sessionmaker: async_sessionmaker[AsyncSession] | None,
) -> async_sessionmaker[AsyncSession]:
    return sessionmaker if sessionmaker is not None else get_sessionmaker()


def _name(row: PrincipalRow | None) -> str:
    if row is None:
        return ""
    return row.display_name or row.email or ""


async def _addresses(
    session: AsyncSession, ids: Sequence[UUID], *, skip: UUID | None
) -> list[tuple[UUID, str]]:
    """Return ``(id, e-mail)`` of the active accounts with an address, without ``skip``."""
    wanted = [pid for pid in dict.fromkeys(ids) if pid != skip]
    if not wanted:
        return []
    rows = (
        await session.execute(
            select(PrincipalRow.id, PrincipalRow.email).where(
                PrincipalRow.id.in_(wanted),
                PrincipalRow.active.is_(True),
                PrincipalRow.merged_into.is_(None),
                PrincipalRow.email.is_not(None),
            )
        )
    ).all()
    found = {pid: str(email) for pid, email in rows if email}
    return [(pid, found[pid]) for pid in wanted if pid in found]


async def _send_each(
    session: AsyncSession,
    *,
    queue: MailQueue | None,
    settings: Settings,
    recipients: list[tuple[UUID, str]],
    key: str,
    subject: dict[str, str],
    body: dict[str, str],
    html: dict[str, str],
    context: dict[str, object],
    message_id: UUID,
    link: MailLink,
) -> int:
    service = NotificationService(session, queue=queue, settings=settings)
    sent = 0
    for pid, address in recipients:
        if await service.send_kind_mail(
            [address],
            kind=MENTION_KIND,
            template_key=key,
            builtin_subject=subject,
            builtin_body=body,
            builtin_html=html,
            context=context,
            idempotency_parts=(key, str(message_id), str(pid)),
            link=link,
        ):
            sent += 1
    return sent


async def send_comment_mentions(
    session: AsyncSession,
    *,
    queue: MailQueue | None,
    settings: Settings,
    comment_id: UUID,
    recipients: Sequence[UUID],
    actor_sub: str,
) -> int:
    """Mail the newly mentioned members of an application comment.

    Returns:
        The number of enqueued mails.
    """
    comment = await session.get(Comment, comment_id)
    if comment is None or not recipients:
        return 0
    still = set(mention_ids(comment.mentions))
    actor = await session.scalar(select(PrincipalRow).where(PrincipalRow.sub == actor_sub))
    targets = await _addresses(
        session,
        [pid for pid in recipients if pid in still],
        skip=actor.id if actor is not None else None,
    )
    if not targets:
        return 0
    data = await session.scalar(
        select(Application.data).where(Application.id == comment.application_id)
    )
    title = (data or {}).get("title")
    files = await FilesService(session).message_attachments("comment", [comment.id])
    text = comment_mail_text(comment.body, [a.filename for a in files.get(comment.id, [])])
    if comment.author_kind == "principal" and comment.author:
        author_row = await session.scalar(
            select(PrincipalRow).where(PrincipalRow.sub == comment.author)
        )
        author = _name(author_row)
    else:
        lang = settings.mail_default_lang
        author = pick_lang(_APPLICANT_AUTHOR_FALLBACK, lang)
    author = author or _name(actor)
    context: dict[str, object] = {
        "actor": _name(actor),
        "applicationId": str(comment.application_id),
        "applicationTitle": title.strip() if isinstance(title, str) else "",
        "comment": text[:_COMMENT_EXCERPT_LEN],
        "commentAuthor": author,
        "commentAuthorInitials": _initials(author),
    }
    return await _send_each(
        session,
        queue=queue,
        settings=settings,
        recipients=targets,
        key=COMMENT_MENTIONED_KEY,
        subject=COMMENT_MENTIONED_SUBJECT,
        body=COMMENT_MENTIONED_BODY,
        html=COMMENT_MENTIONED_HTML,
        context=context,
        message_id=comment.id,
        link=application_link(settings, comment.application_id, guest=False, comment_id=comment.id),
    )


async def notify_comment_mentions(
    *,
    queue: MailQueue | None,
    settings: Settings,
    comment_id: UUID,
    recipients: Sequence[UUID],
    actor_sub: str,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Run `send_comment_mentions` in an own session (best effort).

    Returns:
        The number of enqueued mails, 0 after a failure.
    """
    try:
        async with _maker(sessionmaker)() as session:
            return await send_comment_mentions(
                session,
                queue=queue,
                settings=settings,
                comment_id=comment_id,
                recipients=recipients,
                actor_sub=actor_sub,
            )
    except Exception:
        logger.exception("comment_mentioned mail failed")
        return 0


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
    targets = await _addresses(
        session, [pid for pid in recipients if pid in still], skip=note.author_id
    )
    if not targets:
        return 0
    author = _name(await session.get(PrincipalRow, note.author_id) if note.author_id else None)
    message = note.body
    if not message.strip():
        files = await FilesService(session).message_attachments("ticket_note", [note.id])
        message = comment_mail_text(message, [a.filename for a in files.get(note.id, [])])
    context: dict[str, object] = {
        "actor": author,
        "number": format_number(ticket.number),
        "title": ticket.title,
        "message": message[:_COMMENT_EXCERPT_LEN],
        "author": author,
        "authorInitials": _initials(author),
    }
    return await _send_each(
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
        async with _maker(sessionmaker)() as session:
            return await send_ticket_mentions(
                session, queue=queue, settings=settings, note_id=note_id, recipients=recipients
            )
    except Exception:
        logger.exception("ticket_mentioned mail failed")
        return 0
