"""Anonymization of a ticket (retention cron and erasure): reporter, texts, mails, files."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update

from app.modules.tickets.models import Ticket, TicketEvent, TicketMail, TicketNote
from app.modules.tickets.service.base import TicketServiceBase
from app.modules.tickets.service.common import _now


class AnonymizeOps(TicketServiceBase):
    """The anonymization of one ticket."""

    async def anonymize(self, ticket: Ticket, *, actor: str) -> None:
        """Remove the personal data of a ticket, without a commit.

        The reporter (account and e-mail), the context and the files of the report and
        of every note (rows and objects) go; title, body, the note texts and events
        stay. The public notes of the reporter lose their author: a reporter writes only
        public notes, and an internal note of the same account is the work of a team
        member, who must keep the right to change it. A sender block from this
        ticket stays. The ``created`` event loses its actor, because that actor is the
        reporter and the detail would show the name.
        ``anonymized_at`` marks it.
        """
        notes = select(TicketNote.id).where(TicketNote.ticket_id == ticket.id)
        await self.files.delete_for_ticket(ticket.id, notes=notes, actor=actor)
        if ticket.reporter_principal_id is not None:
            await self.session.execute(
                update(TicketNote)
                .where(
                    TicketNote.ticket_id == ticket.id,
                    TicketNote.author_id == ticket.reporter_principal_id,
                    TicketNote.visibility == "public",
                )
                .values(author_id=None)
            )
        await self.session.execute(
            update(TicketEvent)
            .where(TicketEvent.ticket_id == ticket.id, TicketEvent.kind == "created")
            .values(actor_id=None)
        )
        await self._anonymize_mails(ticket.id)
        for column in ("reporter_principal_id", "reporter_email", "reporter_name"):
            setattr(ticket, column, None)
        ticket.context = {}
        ticket.anonymized_at = _now()

    async def _anonymize_mails(self, ticket_id: uuid.UUID) -> None:
        """Remove the sources and the addresses of the mails of a ticket.

        The row and its ``Message-ID`` stay, so the fetch never imports the mail again
        (§F/integrations/ticket-mail/002724, 002729).
        """
        keys = (
            await self.session.scalars(
                select(TicketMail.source_key).where(
                    TicketMail.ticket_id == ticket_id, TicketMail.source_key.is_not(None)
                )
            )
        ).all()
        await self.files.remove_objects([key for key in keys if key])
        await self.session.execute(
            update(TicketMail)
            .where(TicketMail.ticket_id == ticket_id)
            .values(
                from_address=None,
                from_name=None,
                cc=[],
                to_addresses=[],
                subject=None,
                source_key=None,
                source_scan=None,
                skipped=[],
            )
        )
