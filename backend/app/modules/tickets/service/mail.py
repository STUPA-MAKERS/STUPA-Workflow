"""The mail side of a ticket for the team: answers, resend, mail source, Paperless filing."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence

from sqlalchemy import select

from app.modules.auth.principal import Principal
from app.modules.files.storage import StorageError
from app.modules.tickets.access import AreaScope
from app.modules.tickets.mail_send import (
    MAILBOX_OFF,
    is_mail_ticket,
    mailbox_of,
    send_again,
    thread_recipients,
)
from app.modules.tickets.models import Ticket, TicketMail
from app.modules.tickets.numbers import format_number
from app.modules.tickets.paperless import file_in_paperless
from app.modules.tickets.schemas import TicketMailAnswer, TicketMailOut, TicketPaperlessFile
from app.modules.tickets.service.base import TicketServiceBase
from app.modules.tickets.service.common import MAIL_SOURCE_CLOSED
from app.modules.tickets.service.rows import _mail_out
from app.shared.errors import ConflictError, NotFoundError, ServiceUnavailableError


class MailOps(TicketServiceBase):
    """Mail and Paperless operations on a ticket."""

    async def file_in_paperless(
        self,
        ticket_id: uuid.UUID,
        attachment_id: uuid.UUID,
        principal: Principal,
        *,
        areas: AreaScope = None,
    ) -> TicketPaperlessFile:
        """Open the job that files one file of a ticket in Paperless, without a commit.

        Raises:
            NotFoundError: No ticket has this id in the Bereiche ``areas``, or the ticket
                has no such file (HTTP 404).
            ConflictError: ``paperless_off`` or ``file_not_clean`` (HTTP 409).
        """
        ticket = await self._get(ticket_id, areas=areas)
        return await file_in_paperless(self.session, ticket, attachment_id, actor=principal.sub)

    async def _mail_answer(
        self, ticket: Ticket, mails: Sequence[TicketMail]
    ) -> TicketMailAnswer | None:
        """Return the recipients of the next answer; None when the ticket has no mails."""
        if not is_mail_ticket(ticket):
            return None
        box = await mailbox_of(self.session, ticket)
        people = thread_recipients(ticket, mails, str(box.address) if box is not None else "")
        return TicketMailAnswer(
            to=people.to, cc=people.cc, enabled=box is not None and bool(box.enabled)
        )

    async def resend_mail(
        self, ticket_id: uuid.UUID, mail_id: uuid.UUID, *, areas: AreaScope = None
    ) -> TicketMailOut:
        """Start the send of a failed mail of a ticket again, without a commit.

        Raises:
            NotFoundError: No such ticket in the Bereiche ``areas``, or no such mail on
                it (HTTP 404).
            ConflictError: The mail did not fail (``mail_not_failed``), or the Postfach
                is off (``mailbox_off``) (HTTP 409).
        """
        ticket = await self._get(ticket_id, areas=areas)
        mail = await self.session.get(TicketMail, mail_id, with_for_update=True)
        if mail is None or mail.ticket_id != ticket.id:
            raise NotFoundError("Mail not found.")
        box = await mailbox_of(self.session, ticket)
        if box is None or not box.enabled:
            raise ConflictError("The Postfach of the Bereich is off.", code=MAILBOX_OFF)
        send_again(mail)
        await self.session.flush()
        return _mail_out(mail)

    async def _mails(self, ticket_id: uuid.UUID) -> Sequence[TicketMail]:
        return (
            await self.session.scalars(
                select(TicketMail)
                .where(TicketMail.ticket_id == ticket_id)
                .order_by(TicketMail.created_at, TicketMail.id)
            )
        ).all()

    async def mail_source(
        self, ticket_id: uuid.UUID, mail_id: uuid.UUID, *, areas: AreaScope = None
    ) -> tuple[AsyncIterator[bytes], str, int]:
        """Open the source of a mail of a ticket: the stream, the file name and the size.

        Raises:
            NotFoundError: No such ticket in the Bereiche ``areas``, no such mail on it,
                or the source is gone (HTTP 404).
            ConflictError: The source has no clean scan result
                (``mail_source_closed``, HTTP 409).
            ServiceUnavailableError: The object storage is off (HTTP 503).
        """
        ticket = await self._get(ticket_id, areas=areas)
        mail = await self.session.get(TicketMail, mail_id)
        if mail is None or mail.ticket_id != ticket.id or mail.source_key is None:
            raise NotFoundError("Mail not found.")
        if mail.source_scan != "clean":
            raise ConflictError(
                "The source of the mail has no clean scan result.", code=MAIL_SOURCE_CLOSED
            )
        if self.files.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        try:
            stream = await self.files.storage.get_stream(mail.source_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Mail source temporarily unavailable.") from exc
        return stream, f"{format_number(ticket.number)}.eml", mail.source_size
