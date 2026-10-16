"""Ticket mails: ``ticket_created`` and ``ticket_message`` to the team,
``ticket_received`` and ``ticket_answer`` to the reporter.

All run as background tasks after the commit of the report or the message, each
with its own session, and all are best effort: a mail failure never fails the
request.

``ticket_created`` goes to the holders of ``ticket.manage`` while
``tickets.notifyNew`` is on, without the reporter; each holder can switch it off
(kind ``ticket_created``). ``ticket_received`` confirms the report to the reporter
with the number and the handbook link. Its kind is not in ``NOTIFICATION_KINDS``, so
nobody can switch it off. A report without a session can name any address, so for
it the mail leaves out the title (``title`` is empty): the platform does not send
text of the caller to an address that nobody checked. Only a report of an account
links the ticket, because only an account reads it again in the tab "Tickets"; a
report without a session stays one-way. The language is ``context.language``, else
German.

``ticket_answer`` goes to the reporter account when the team writes a ``public``
note. ``ticket_message`` goes to the team when the reporter writes: to the assignee
while one holds ``ticket.manage``, else to every holder. An internal note, an edit
and a note on an anonymized ticket send nothing. Each recipient can switch the kind
off. A team author shows by name only, never by e-mail, as in the tab.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.admin.site_config_service import active_branding
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.files.service import FilesService
from app.modules.notifications.links import ticket_link
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.tickets.models import Ticket, TicketNote
from app.modules.tickets.service import TicketService, format_number, ticket_managers
from app.settings import Settings

logger = logging.getLogger("app.tickets")

TICKET_CREATED_KEY = "ticket_created"
TICKET_RECEIVED_KEY = "ticket_received"
TICKET_ANSWER_KEY = "ticket_answer"
TICKET_MESSAGE_KEY = "ticket_message"

_KIND_DE = (
    "{% if kind == 'bug' %}Problem{% elif kind == 'question' %}Frage{% else %}Idee{% endif %}"
)
_KIND_EN = (
    "{% if kind == 'bug' %}problem{% elif kind == 'question' %}question{% else %}idea{% endif %}"
)

TICKET_CREATED_SUBJECT: dict[str, str] = {
    "de": "Neues Ticket {{ number }}: {{ title }}",
    "en": "New ticket {{ number }}: {{ title }}",
}
TICKET_CREATED_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ reporter }} hat ein neues Ticket gemeldet (" + _KIND_DE + "):\n\n"
    "{{ number }} · {{ title }}\n",
    "en": "Hello,\n\n{{ reporter }} reported a new ticket (" + _KIND_EN + "):\n\n"
    "{{ number }} · {{ title }}\n",
}
TICKET_CREATED_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Ticket (ohne den Platzhalter hängt die Mail ihn an)",
    "number": "Ticketnummer (T-0042)",
    "title": "Titel des Tickets",
    "kind": "Art (bug/question/idea)",
    "reporter": "Name oder E-Mail der meldenden Person",
}

TICKET_RECEIVED_SUBJECT: dict[str, str] = {
    "de": "Ihre Meldung {{ number }} ist eingegangen",
    "en": "Your report {{ number }} was received",
}
TICKET_RECEIVED_BODY: dict[str, str] = {
    "de": "Hallo,\n\nvielen Dank für Ihre Meldung{% if title %} „{{ title }}“{% endif %}. "
    "Sie hat die Nummer "
    "{{ number }}. {% if link %}Antworten und den Stand finden Sie unter „Tickets“."
    "{% else %}Bei Rückfragen melden wir uns per E-Mail.{% endif %}\n\n"
    "Antworten auf viele Fragen stehen im Handbuch: {{ wikiUrl }}\n",
    "en": "Hello,\n\nthank you for your report"
    '{% if title %} "{{ title }}"{% endif %}. Its number is '
    "{{ number }}. {% if link %}You find the answers and the status under "
    '"Tickets".{% else %}If we have questions, we will contact you by email.{% endif %}'
    "\n\n"
    "The handbook answers many questions: {{ wikiUrl }}\n",
}
TICKET_RECEIVED_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Ticket (leer bei einer Meldung ohne Anmeldung)",
    "number": "Ticketnummer (T-0042)",
    "title": "Titel des Tickets (leer bei einer Meldung ohne Anmeldung)",
    "wikiUrl": "Link zum Handbuch",
}


TICKET_ANSWER_SUBJECT: dict[str, str] = {
    "de": "Antwort auf Ihr Ticket {{ number }}",
    "en": "Reply to your ticket {{ number }}",
}
TICKET_ANSWER_BODY: dict[str, str] = {
    "de": "Hallo,\n\nzu Ihrem Ticket {{ number }} „{{ title }}“ gibt es eine neue "
    "Nachricht{% if author %} von {{ author }}{% endif %}:\n\n{{ message }}\n",
    "en": 'Hello,\n\nthere is a new message on your ticket {{ number }} "{{ title }}"'
    "{% if author %} from {{ author }}{% endif %}:\n\n{{ message }}\n",
}
TICKET_ANSWER_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Ticket (ohne den Platzhalter hängt die Mail ihn an)",
    "number": "Ticketnummer (T-0042)",
    "title": "Titel des Tickets",
    "author": "Name des Teammitglieds (leer ohne Namen)",
    "message": "Text der Nachricht (ohne Text die Namen der Dateien)",
}

TICKET_MESSAGE_SUBJECT: dict[str, str] = {
    "de": "Neue Nachricht zu Ticket {{ number }}: {{ title }}",
    "en": "New message on ticket {{ number }}: {{ title }}",
}
TICKET_MESSAGE_BODY: dict[str, str] = {
    "de": "Hallo,\n\n{{ reporter }} hat zum Ticket {{ number }} „{{ title }}“ "
    "geschrieben:\n\n{{ message }}\n",
    "en": 'Hello,\n\n{{ reporter }} wrote on the ticket {{ number }} "{{ title }}":'
    "\n\n{{ message }}\n",
}
TICKET_MESSAGE_PLACEHOLDERS: dict[str, str] = {
    "link": "Link zum Ticket (ohne den Platzhalter hängt die Mail ihn an)",
    "number": "Ticketnummer (T-0042)",
    "title": "Titel des Tickets",
    "reporter": "Name oder E-Mail der meldenden Person",
    "message": "Text der Nachricht (ohne Text die Namen der Dateien)",
}


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
    """Mail a new ticket to the holders of ``ticket.manage`` (best effort).

    Returns:
        True when a mail was enqueued.
    """
    try:
        async with _maker(sessionmaker)() as session:
            branding = await active_branding(session)
            ticket = await session.get(Ticket, ticket_id)
            if ticket is None or not branding.tickets.notify_new:
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
                    for _pid, _name, email in await ticket_managers(session)
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
                    "kind": ticket.kind,
                    "reporter": reporter,
                },
                idempotency_parts=(TICKET_CREATED_KEY, str(ticket.id)),
                link=ticket_link(settings, ticket.id),
            )
    except Exception:  # noqa: BLE001 - a mail must never break the report
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
            # Only an account reads the ticket again, in the tab "Tickets".
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
                    # A report without a session names an unchecked address, so
                    # its mail carries no text of the caller.
                    "title": ticket.title if ticket.reporter_principal_id else "",
                    "wikiUrl": branding.help.wiki_url,
                },
                idempotency_parts=(TICKET_RECEIVED_KEY, str(ticket.id)),
                lang=language if language in ("de", "en") else "de",
                link=link,
            )
    except Exception:  # noqa: BLE001 - a mail must never break the report
        logger.exception("ticket_received mail failed")
        return False


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
            message = note.body
            if not message.strip():
                # A message of files only names its files, as the comment mails do.
                files = await FilesService(session).message_attachments("ticket_note", [note.id])
                message = ", ".join(a.filename for a in files.get(note.id, []))
            if note.author_id == ticket.reporter_principal_id:
                return await _mail_team(session, queue, settings, ticket, note, message)
            return await _mail_reporter(session, queue, settings, ticket, note, message)
    except Exception:  # noqa: BLE001 - a mail must never break the message
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
    managers = await ticket_managers(session)
    assignee = [m for m in managers if m[0] == ticket.assignee_id]
    reporter_row = await session.get(PrincipalRow, ticket.reporter_principal_id)
    own = (reporter_row.email or "").casefold() if reporter_row is not None else ""
    recipients = sorted(
        {
            email
            for _pid, _name, email in (assignee or managers)
            if email and email.casefold() != own
        }
    )
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
    address = await TicketService(session).reporter_address(ticket)
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
            # The name only: the e-mail of a team member never reaches the reporter.
            "author": (author.display_name or "") if author is not None else "",
            "message": message,
        },
        idempotency_parts=(TICKET_ANSWER_KEY, str(note.id)),
        lang=language if language in ("de", "en") else "de",
        link=ticket_link(settings, ticket.id),
    )
