"""Termin mails: the invitation, the change and the deletion.

The router sends them after the commit as a background task with its own session, and
they are best effort: a mail failure never fails the write. The three templates are
one notification kind (``appointment``), so a person switches all of them off at once.
Each person gets an own mail, because the attached ``.ics`` file names the recipient as
``ATTENDEE`` with the answer of that person. The mail of a deleted Termin has no link.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.calendar.appointments import AppointmentFacts, AppointmentMail
from app.modules.calendar.ics import AppointmentEvent, build_appointment_file
from app.modules.calendar.models import Answer
from app.modules.calendar.rules import Span
from app.modules.notifications.links import appointment_link
from app.modules.notifications.mail import MailAttachment
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.notifications.texts.calendar import (
    APPOINTMENT_CANCELLED_BODY,
    APPOINTMENT_CANCELLED_KEY,
    APPOINTMENT_CANCELLED_SUBJECT,
    APPOINTMENT_CHANGED_BODY,
    APPOINTMENT_CHANGED_KEY,
    APPOINTMENT_CHANGED_SUBJECT,
    APPOINTMENT_INVITED_BODY,
    APPOINTMENT_INVITED_KEY,
    APPOINTMENT_INVITED_SUBJECT,
    APPOINTMENT_KIND,
)
from app.settings import Settings

logger = logging.getLogger("app.calendar")

#: The template key, the subject and the body of each mail kind.
_TEXTS: dict[str, tuple[str, dict[str, str], dict[str, str]]] = {
    "invited": (APPOINTMENT_INVITED_KEY, APPOINTMENT_INVITED_SUBJECT, APPOINTMENT_INVITED_BODY),
    "changed": (APPOINTMENT_CHANGED_KEY, APPOINTMENT_CHANGED_SUBJECT, APPOINTMENT_CHANGED_BODY),
    "cancelled": (
        APPOINTMENT_CANCELLED_KEY,
        APPOINTMENT_CANCELLED_SUBJECT,
        APPOINTMENT_CANCELLED_BODY,
    ),
}


def when_text(span: Span) -> str:
    """The start and the end of a Termin as one line, for example ``20.11.2026 14:00 – 16:00``."""
    first = span.starts_on.strftime("%d.%m.%Y")
    last = span.ends_on.strftime("%d.%m.%Y")
    if span.start_time is None or span.end_time is None:
        return first if span.ends_on == span.starts_on else f"{first} – {last}"
    start = f"{first} {span.start_time:%H:%M}"
    return (
        f"{start} – {span.end_time:%H:%M}"
        if span.ends_on == span.starts_on
        else f"{start} – {last} {span.end_time:%H:%M}"
    )


def ics_file(
    facts: AppointmentFacts, *, domain: str, attendee: str, answer: str | None, cancelled: bool
) -> MailAttachment:
    """The Termin as the ``.ics`` attachment of the mail to one person."""
    return MailAttachment(
        filename="termin.ics",
        mime="text/calendar",
        content=build_appointment_file(
            AppointmentEvent(
                uid=str(facts.id),
                title=facts.title,
                starts_on=facts.span.starts_on,
                ends_on=facts.span.ends_on,
                start_time=facts.span.start_time,
                end_time=facts.span.end_time,
                stamp=facts.created_at,
                place=facts.span.place,
                description=facts.description,
                sequence=facts.sequence,
                attendee=attendee,
                answer=answer,
                cancelled=cancelled,
            ),
            domain=domain,
        ),
    )


async def send_appointment_mail(
    session: AsyncSession, *, queue: MailQueue | None, settings: Settings, mail: AppointmentMail
) -> int:
    """Send one mail of the outbox to each of its recipients with an address.

    Returns:
        The number of enqueued mails.
    """
    people = (
        await session.execute(
            select(PrincipalRow.id, PrincipalRow.email).where(
                PrincipalRow.id.in_(mail.recipients),
                PrincipalRow.active.is_(True),
                PrincipalRow.email.is_not(None),
            )
        )
    ).all()
    actor = await session.get(PrincipalRow, mail.actor_id)
    answers = dict(
        (
            await session.execute(
                select(Answer.principal_id, Answer.answer).where(
                    Answer.appointment_id == mail.facts.id
                )
            )
        ).all()
    )
    key, subject, body = _TEXTS[mail.kind]
    cancelled = mail.kind == "cancelled"
    service = NotificationService(session, queue=queue, settings=settings)
    domain = urlsplit(settings.public_base_url).hostname or "stupa.local"
    sent = [
        await service.send_kind_mail(
            [str(email)],
            kind=APPOINTMENT_KIND,
            template_key=key,
            builtin_subject=subject,
            builtin_body=body,
            context={
                "title": mail.facts.title,
                "when": when_text(mail.facts.span),
                "place": mail.facts.span.place or "",
                "actor": (actor.display_name or "") if actor is not None else "",
            },
            idempotency_parts=(key, str(mail.facts.id), str(person_id), str(mail.event_id)),
            link=None if cancelled else appointment_link(settings, mail.facts.id),
            attachments=(
                ics_file(
                    mail.facts,
                    domain=domain,
                    attendee=str(email),
                    answer=answers.get(person_id),
                    cancelled=cancelled,
                ),
            ),
        )
        for person_id, email in people
        if email
    ]
    return sum(sent)


async def notify_appointment_mails(
    *,
    queue: MailQueue | None,
    settings: Settings,
    mails: Sequence[AppointmentMail],
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Send the mails of a write (best effort).

    Returns:
        The number of enqueued mails.
    """
    maker = sessionmaker if sessionmaker is not None else get_sessionmaker()

    async def send_one(mail: AppointmentMail) -> int:
        try:
            async with maker() as session:
                return await send_appointment_mail(
                    session, queue=queue, settings=settings, mail=mail
                )
        except Exception:
            logger.exception("%s mail failed", mail.kind)
            return 0

    return sum([await send_one(mail) for mail in mails])
