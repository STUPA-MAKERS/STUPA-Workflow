"""Ticket mails: ``ticket_created`` to the team, ``ticket_received`` to the reporter.

Both run as background tasks after the commit of the report, each with its own
session, and both are best effort: a mail failure never fails the report.

``ticket_created`` goes to the holders of ``ticket.manage`` while
``tickets.notifyNew`` is on, without the reporter; each holder can switch it off
(kind ``ticket_created``). ``ticket_received`` confirms the report to the reporter
with the number and the handbook link. Its kind is not in ``NOTIFICATION_KINDS``, so
nobody can switch it off. The mail has no link to the ticket, because the reporter
never reads it again (one-way); the language is ``context.language``, else German.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.admin.site_config_service import active_branding
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.notifications.links import ticket_link
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.tickets.models import Ticket
from app.modules.tickets.service import TicketService, format_number, ticket_managers
from app.settings import Settings

logger = logging.getLogger("app.tickets")

TICKET_CREATED_KEY = "ticket_created"
TICKET_RECEIVED_KEY = "ticket_received"

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
    "de": "Hallo,\n\nvielen Dank für Ihre Meldung „{{ title }}“. Sie hat die Nummer "
    "{{ number }}. Bei Rückfragen melden wir uns per E-Mail.\n\n"
    "Antworten auf viele Fragen stehen im Handbuch: {{ wikiUrl }}\n",
    "en": 'Hello,\n\nthank you for your report "{{ title }}". Its number is '
    "{{ number }}. If we have questions, we will contact you by email.\n\n"
    "The handbook answers many questions: {{ wikiUrl }}\n",
}
TICKET_RECEIVED_PLACEHOLDERS: dict[str, str] = {
    "number": "Ticketnummer (T-0042)",
    "title": "Titel des Tickets",
    "wikiUrl": "Link zum Handbuch",
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
                    "title": ticket.title,
                    "wikiUrl": branding.help.wiki_url,
                },
                idempotency_parts=(TICKET_RECEIVED_KEY, str(ticket.id)),
                lang=language if language in ("de", "en") else "de",
            )
    except Exception:  # noqa: BLE001 - a mail must never break the report
        logger.exception("ticket_received mail failed")
        return False
