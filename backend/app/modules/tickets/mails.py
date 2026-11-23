"""Send the ticket mails to the team and to the reporter.

``ticket_created``, ``ticket_message`` and ``ticket_assigned`` go to the team,
``ticket_received`` and ``ticket_answer`` to the reporter.

All run as background tasks after the commit of the report or the message, each
with its own session, and all are best effort: a mail failure never fails the
request.

``ticket_created`` goes to the persons with the work right in the Bereich of the
ticket while the switch ``notify_new`` of the Bereich is on, without the reporter;
each person can switch it off (kind ``ticket_created``). ``ticket_received`` confirms
the report to the reporter
with the number and the handbook link. Its kind is not in ``NOTIFICATION_KINDS``, so
nobody can switch it off. A report without a session can name any address, so for
it the mail leaves out the title (``title`` is empty): the platform does not send
text of the caller to an address that nobody checked. Only a report of an account
links the ticket, because only an account reads it again in the tab "Tickets"; a
report without a session stays one-way. The language is ``context.language``, else
German.

``ticket_answer`` goes to the reporter account when the team writes a ``public``
note. ``ticket_message`` goes to the team when the reporter writes: to the assignee
while the person has the work right in the Bereich, else to every person with it. An
internal note, an edit,
a note on an anonymized ticket and an answer to a deactivated or merged reporter account
send nothing. Each recipient can switch the kind
off. A team author shows by name only, never by e-mail, as in the tab.

``ticket_assigned`` goes to the new assignee when a different person assigned the
ticket. A person who takes a ticket gets no mail. The mail reads the newest
``assignee`` event of the ticket and is idempotent for that event, so a change that
does not touch the assignee sends nothing new.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.files.service import FilesService
from app.modules.notifications.links import ticket_link
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.notifications.texts.tickets import (
    TICKET_ANSWER_BODY,
    TICKET_ANSWER_KEY,
    TICKET_ANSWER_SUBJECT,
    TICKET_ASSIGNED_BODY,
    TICKET_ASSIGNED_KEY,
    TICKET_ASSIGNED_SUBJECT,
    TICKET_CREATED_BODY,
    TICKET_CREATED_KEY,
    TICKET_CREATED_SUBJECT,
    TICKET_MESSAGE_BODY,
    TICKET_MESSAGE_KEY,
    TICKET_MESSAGE_SUBJECT,
    TICKET_RECEIVED_BODY,
    TICKET_RECEIVED_KEY,
    TICKET_RECEIVED_SUBJECT,
)
from app.modules.site_config.reads import active_branding
from app.modules.tickets.access import area_workers
from app.modules.tickets.models import (
    PLATFORM_AREA_ID,
    Ticket,
    TicketArea,
    TicketEvent,
    TicketNote,
)
from app.modules.tickets.service import TicketService, format_number
from app.settings import Settings

logger = logging.getLogger("app.tickets")


def _maker(
    sessionmaker: async_sessionmaker[AsyncSession] | None,
) -> async_sessionmaker[AsyncSession]:
    return sessionmaker if sessionmaker is not None else get_sessionmaker()


async def notify_ticket_created(
    *,
    queue: MailQueue | None,
    settings: Settings,
    ticket_id: UUID,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    """Mail a new ticket to the team of its Bereich (best effort).

    Returns:
        True when a mail was enqueued.
    """
    try:
        async with _maker(sessionmaker)() as session:
            ticket = await session.get(Ticket, ticket_id)
            area = (
                await session.get(TicketArea, ticket.area_id or PLATFORM_AREA_ID)
                if ticket is not None
                else None
            )
            if ticket is None or area is None or not area.notify_new:
                return False
            reporter_address = await TicketService(session).reporter_address(ticket)
            reporter_name = (
                await session.get(PrincipalRow, ticket.reporter_principal_id)
                if ticket.reporter_principal_id is not None
                else None
            )
            reporter = (
                (reporter_name.display_name if reporter_name is not None else None)
                or reporter_address
                or ""
            )
            own = (reporter_address or "").casefold()
            recipients = sorted(
                {
                    email
                    for _pid, _name, email in await area_workers(session, frozenset({area.id}))
                    if email and email.casefold() != own
                }
            )
            if not recipients:
                return False
            return await NotificationService(
                session, queue=queue, settings=settings
            ).send_kind_mail(
                recipients,
                kind=TICKET_CREATED_KEY,
                template_key=TICKET_CREATED_KEY,
                builtin_subject=TICKET_CREATED_SUBJECT,
                builtin_body=TICKET_CREATED_BODY,
                context={
                    "number": format_number(ticket.number),
                    "title": ticket.title,
                    "kind": ticket.kind or "",
                    "area": area.name,
                    "reporter": reporter,
                },
                idempotency_parts=(TICKET_CREATED_KEY, str(ticket.id)),
                link=ticket_link(settings, ticket.id),
            )
    except Exception:
        logger.exception("ticket_created mail failed")
        return False


async def notify_ticket_received(
    *,
    queue: MailQueue | None,
    settings: Settings,
    ticket_id: UUID,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    """Confirm a report to its reporter with the number and the handbook link.

    Returns:
        True when a mail was enqueued.

    Only an account gets the link, because only an account reads the ticket again (tab
    "Tickets"). A report without a session names an unchecked address, so its mail carries
    no text of the caller.
    """
    try:
        async with _maker(sessionmaker)() as session:
            ticket = await session.get(Ticket, ticket_id)
            if ticket is None:
                return False
            address = await TicketService(session).reporter_address(ticket)
            if not address:
                return False
            branding = await active_branding(session)
            language = (ticket.context or {}).get("language")
            link = (
                ticket_link(settings, ticket.id)
                if ticket.reporter_principal_id is not None
                else None
            )
            return await NotificationService(
                session, queue=queue, settings=settings
            ).send_kind_mail(
                [address],
                kind=TICKET_RECEIVED_KEY,
                template_key=TICKET_RECEIVED_KEY,
                builtin_subject=TICKET_RECEIVED_SUBJECT,
                builtin_body=TICKET_RECEIVED_BODY,
                context={
                    "number": format_number(ticket.number),
                    "title": ticket.title if ticket.reporter_principal_id else "",
                    "wikiUrl": branding.help.wiki_url,
                },
                idempotency_parts=(TICKET_RECEIVED_KEY, str(ticket.id)),
                lang=language or "de",
                link=link,
            )
    except Exception:
        logger.exception("ticket_received mail failed")
        return False


async def _note_filenames(session: AsyncSession, note: TicketNote) -> list[str]:
    """Return the file names of the attachments of a ticket note."""
    files = await FilesService(session).message_attachments("ticket_note", [note.id])
    return [a.filename for a in files.get(note.id, [])]


async def notify_ticket_note(
    *,
    queue: MailQueue | None,
    settings: Settings,
    note_id: UUID,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    """Mail a new public message to the other side of the ticket (best effort).

    A message of the reporter goes to the team (``ticket_message``), a public note
    of the team to the reporter account (``ticket_answer``).

    Returns:
        True when a mail was enqueued.

    A message of files only names its files, as the comment mails do; a message without text
    and files sends nothing.
    """
    try:
        async with _maker(sessionmaker)() as session:
            note = await session.get(TicketNote, note_id)
            if note is None or note.deleted_at is not None or note.visibility != "public":
                return False
            ticket = await session.get(Ticket, note.ticket_id)
            if (
                ticket is None
                or ticket.anonymized_at is not None
                or ticket.reporter_principal_id is None
            ):
                return False
            message = (
                note.body if note.body.strip() else ", ".join(await _note_filenames(session, note))
            )
            if not message.strip():
                return False
            if note.author_id == ticket.reporter_principal_id:
                return await _mail_team(session, queue, settings, ticket, note, message)
            return await _mail_reporter(session, queue, settings, ticket, note, message)
    except Exception:
        logger.exception("ticket note mail failed")
        return False


async def _mail_team(
    session: AsyncSession,
    queue: MailQueue | None,
    settings: Settings,
    ticket: Ticket,
    note: TicketNote,
    message: str,
) -> bool:
    """Mail the assignee, else every holder; an assignee without an address falls back.

    The assignee's own opt-out of ``ticket_message`` stays an opt-out: the mail then
    reaches nobody, as the assignee chose.
    """
    managers = await area_workers(session, frozenset({ticket.area_id or PLATFORM_AREA_ID}))
    reporter_row = await session.get(PrincipalRow, ticket.reporter_principal_id)
    own = (reporter_row.email or "").casefold() if reporter_row is not None else ""

    def _addresses(rows: list[tuple[UUID, str | None, str | None]]) -> list[str]:
        return sorted({e for _pid, _name, e in rows if e and e.casefold() != own})

    assignee = [m for m in managers if m[0] == ticket.assignee_id]
    recipients = _addresses(assignee) or _addresses(managers)
    if not recipients:
        return False
    reporter = (
        (reporter_row.display_name or reporter_row.email or "") if reporter_row is not None else ""
    )
    return await NotificationService(session, queue=queue, settings=settings).send_kind_mail(
        recipients,
        kind=TICKET_MESSAGE_KEY,
        template_key=TICKET_MESSAGE_KEY,
        builtin_subject=TICKET_MESSAGE_SUBJECT,
        builtin_body=TICKET_MESSAGE_BODY,
        context={
            "number": format_number(ticket.number),
            "title": ticket.title,
            "reporter": reporter,
            "message": message,
        },
        idempotency_parts=(TICKET_MESSAGE_KEY, str(note.id)),
        link=ticket_link(settings, ticket.id),
    )


async def _mail_reporter(
    session: AsyncSession,
    queue: MailQueue | None,
    settings: Settings,
    ticket: Ticket,
    note: TicketNote,
    message: str,
) -> bool:
    """Mail a public team note to the reporter account (``ticket_answer``).

    Only a live account gets it, because a deactivated or merged one cannot open the link.
    The mail names the author by name only, so the e-mail of a team member never reaches the
    reporter.
    """
    reporter = await session.get(PrincipalRow, ticket.reporter_principal_id)
    if reporter is None or not reporter.active or reporter.merged_into is not None:
        return False
    address = reporter.email
    if not address:
        return False
    author = await session.get(PrincipalRow, note.author_id) if note.author_id is not None else None
    language = (ticket.context or {}).get("language")
    return await NotificationService(session, queue=queue, settings=settings).send_kind_mail(
        [address],
        kind=TICKET_ANSWER_KEY,
        template_key=TICKET_ANSWER_KEY,
        builtin_subject=TICKET_ANSWER_SUBJECT,
        builtin_body=TICKET_ANSWER_BODY,
        context={
            "number": format_number(ticket.number),
            "title": ticket.title,
            "author": (author.display_name or "") if author is not None else "",
            "message": message,
        },
        idempotency_parts=(TICKET_ANSWER_KEY, str(note.id)),
        lang=language or "de",
        link=ticket_link(settings, ticket.id),
    )


async def notify_ticket_assigned(
    *,
    queue: MailQueue | None,
    settings: Settings,
    ticket_id: UUID,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    """Mail the new assignee of a ticket when a different person assigned it (best effort).

    Returns:
        True when a mail was enqueued.
    """
    try:
        async with _maker(sessionmaker)() as session:
            ticket = await session.get(Ticket, ticket_id)
            event = await session.scalar(
                select(TicketEvent)
                .where(TicketEvent.ticket_id == ticket_id, TicketEvent.kind == "assignee")
                .order_by(TicketEvent.created_at.desc(), TicketEvent.id.desc())
                .limit(1)
            )
            if ticket is None or event is None or ticket.assignee_id is None:
                return False
            target = str(ticket.assignee_id)
            if (event.payload or {}).get("to") != target or str(event.actor_id) == target:
                return False
            workers = await area_workers(
                session,
                frozenset({ticket.area_id or PLATFORM_AREA_ID}),
                principal_id=ticket.assignee_id,
            )
            recipients = sorted({email for _pid, _name, email in workers if email})
            if not recipients:
                return False
            actor = (
                await session.get(PrincipalRow, event.actor_id)
                if event.actor_id is not None
                else None
            )
            return await NotificationService(
                session, queue=queue, settings=settings
            ).send_kind_mail(
                recipients,
                kind=TICKET_ASSIGNED_KEY,
                template_key=TICKET_ASSIGNED_KEY,
                builtin_subject=TICKET_ASSIGNED_SUBJECT,
                builtin_body=TICKET_ASSIGNED_BODY,
                context={
                    "number": format_number(ticket.number),
                    "title": ticket.title,
                    "actor": (actor.display_name or "") if actor is not None else "",
                },
                idempotency_parts=(TICKET_ASSIGNED_KEY, str(event.id)),
                link=ticket_link(settings, ticket.id),
            )
    except Exception:
        logger.exception("ticket_assigned mail failed")
        return False
