"""Turn one mail of a Postfach into a ticket, a message or an event.

``MailImporter.take`` decides in this order, and it never commits:

1. A mail without a sender, and a mail from the address of the Postfach itself, stays
   in the inbox.
2. A mail whose identity the Postfach already has is imported
   (§F/integrations/ticket-mail/002724).
3. A mail of a blocked sender counts on the block and makes nothing
   (§F/integrations/ticket-mail/002740).
4. A mail whose ``In-Reply-To`` or ``References`` names a stored mail of the Postfach
   belongs to that ticket; the newest ticket wins (§F/integrations/ticket-mail/002726).
5. An automatic mail becomes an event of its ticket, else it stays in the inbox
   (§F/integrations/ticket-mail/002732).
6. A mail with the number of a ticket of the Bereich in its subject belongs to that
   ticket when its sender is the sender or a ``Cc`` address of the ticket
   (§F/integrations/ticket-mail/002727).
7. Each other mail becomes a new ticket (§F/integrations/ticket-mail/002725), at most
   ``TICKETS_PER_HOUR`` an hour for one address; a mail above the limit stays in the
   inbox (§F/integrations/ticket-mail/002741).

A mail for an anonymized ticket becomes a new ticket, because an anonymized ticket takes
no person and no file. A mail for a ticket that is closed for more than ``REOPEN_DAYS``
days becomes a follow-up ticket, like a late message in the app.

The sender of a ticket from a mail is the ``From`` address and never an account
(§F/integrations/ticket-mail/002739), because nothing checks the ``From`` of a mail.

The full source goes to the object storage (§F/integrations/ticket-mail/002729). Each
attachment and each inline image becomes a file of the message with the scan of each
upload. A file above the size limit or of a type that an upload refuses is left out and
named in ``ticket_mail.skipped`` (§F/integrations/ticket-mail/002730).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.files.models import Attachment
from app.modules.files.scanner import ScannerError, VirusScanner
from app.modules.files.service import FilesService
from app.modules.tickets.mail_parse import MailFile, ParsedMail
from app.modules.tickets.mail_send import queue_confirmation
from app.modules.tickets.models import (
    Ticket,
    TicketMail,
    TicketMailbox,
    TicketNote,
)
from app.modules.tickets.service import TicketService, format_number, reply_is_late
from app.modules.tickets.webhook_fields import emit_ticket_created
from app.shared.errors import AppError
from app.shared.filenames import sanitize_storage_name

logger = logging.getLogger("app.tickets")

#: The new tickets that the mails of one address open in an hour.
TICKETS_PER_HOUR = 20
#: The MIME type of the source of a mail.
SOURCE_MIME = "message/rfc822"
#: The prefix of the storage key of a source.
SOURCE_PREFIX = "ticket-mail/"

TakenKind = Literal["ticket", "message", "event", "duplicate", "blocked", "deferred", "ignored"]
#: The outcomes after which the mail leaves the inbox.
_MOVED: frozenset[str] = frozenset({"ticket", "message", "event", "duplicate", "blocked"})


@dataclass(frozen=True, slots=True)
class Taken:
    """What became of one mail.

    Attributes:
        kind: ``ticket`` (a new ticket), ``message`` (a message of a ticket), ``event``
            (an automatic mail of a ticket), ``duplicate``, ``blocked``, ``deferred``
            (above the rate limit) or ``ignored``.
        attachment_ids: The new files, which need a scan after the commit.
    """

    kind: TakenKind
    ticket_id: uuid.UUID | None = None
    note_id: uuid.UUID | None = None
    attachment_ids: tuple[uuid.UUID, ...] = ()

    @property
    def moves(self) -> bool:
        """Tell if the mail goes to the folder for done mails."""
        return self.kind in _MOVED


@dataclass(frozen=True, slots=True)
class _Stored:
    """The files of one mail after the storage."""

    attachment_ids: tuple[uuid.UUID, ...]
    skipped: tuple[dict[str, str | int], ...]


@dataclass(frozen=True, slots=True)
class MailImporter:
    """Import mails bound to a session, the file service and the virus scanner."""

    session: AsyncSession
    files: FilesService
    scanner: VirusScanner | None = None

    @property
    def _tickets(self) -> TicketService:
        return TicketService(self.session, files=self.files)

    async def take(self, box: TicketMailbox, mail: ParsedMail, source: bytes) -> Taken:
        """Import one mail without a commit and say what became of it."""
        if not mail.sender or mail.sender == str(box.address).strip().lower():
            return Taken("ignored")
        if await self._known(box, mail.identity):
            return Taken("duplicate")
        block = await self._tickets.matching_block(reporter_id=None, email=mail.sender)
        if block is not None:
            await self._tickets.count_block_hit(block)
            return Taken("blocked")
        by_header = await self._by_headers(box, mail.parents)
        if mail.automatic:
            return (
                await self._as_event(box, by_header, mail, source)
                if by_header is not None
                else Taken("ignored")
            )
        ticket = by_header or await self._by_number(box, mail)
        if ticket is not None and not reply_is_late(ticket):
            return await self._as_message(box, ticket, mail, source)
        if await self._over_limit(mail.sender):
            return Taken("deferred")
        return await self._as_ticket(box, mail, source, follows=ticket)

    async def _known(self, box: TicketMailbox, identity: str) -> bool:
        found = await self.session.scalar(
            select(TicketMail.id)
            .where(TicketMail.mailbox_id == box.id, TicketMail.message_id == identity)
            .limit(1)
        )
        return found is not None

    async def _by_headers(self, box: TicketMailbox, parents: tuple[str, ...]) -> Ticket | None:
        """Return the newest ticket that has one of the named mails, else None."""
        if not parents:
            return None
        return await self.session.scalar(
            select(Ticket)
            .join(TicketMail, TicketMail.ticket_id == Ticket.id)
            .where(
                TicketMail.mailbox_id == box.id,
                TicketMail.message_id.in_(parents),
                Ticket.anonymized_at.is_(None),
            )
            .order_by(Ticket.created_at.desc(), Ticket.id)
            .limit(1)
            .with_for_update(of=Ticket)
        )

    async def _by_number(self, box: TicketMailbox, mail: ParsedMail) -> Ticket | None:
        """Return the ticket of the number in the subject for a participant, else None."""
        if mail.number is None:
            return None
        ticket = await self.session.scalar(
            select(Ticket)
            .where(
                Ticket.number == mail.number,
                Ticket.area_id == box.area_id,
                Ticket.anonymized_at.is_(None),
            )
            .with_for_update()
        )
        if ticket is None:
            return None
        return ticket if await self._takes_part(ticket, mail.sender) else None

    async def _takes_part(self, ticket: Ticket, address: str) -> bool:
        """Tell if ``address`` is the sender or a ``Cc`` address of the ticket."""
        sender = (await self._tickets.reporter_address(ticket) or "").strip().lower()
        if sender and sender == address:
            return True
        lists = (
            await self.session.scalars(
                select(TicketMail.cc).where(TicketMail.ticket_id == ticket.id)
            )
        ).all()
        return any(address == str(entry).strip().lower() for cc in lists for entry in cc or [])

    async def _over_limit(self, address: str) -> bool:
        count = await self.session.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(
                Ticket.source == "mail",
                Ticket.reporter_email == address,
                Ticket.created_at > func.now() - timedelta(hours=1),
            )
        )
        return (count or 0) >= TICKETS_PER_HOUR

    async def _as_ticket(
        self, box: TicketMailbox, mail: ParsedMail, source: bytes, *, follows: Ticket | None
    ) -> Taken:
        ticket = Ticket(
            id=uuid.uuid4(),
            number=await self._tickets.free_number(),
            area_id=box.area_id,
            kind=None,
            category_id=follows.category_id if follows is not None else None,
            source="mail",
            title=mail.title,
            body=mail.text,
            status="new",
            reporter_email=mail.sender,
            reporter_name=mail.sender_name or None,
            follow_up_of_id=follows.id if follows is not None else None,
            context={},
        )
        self.session.add(ticket)
        await self.session.flush()
        stored = await self._store_files(mail.files, ticket_id=ticket.id)
        await self._record(box, ticket.id, None, mail, source, stored)
        await emit_ticket_created(self.session, ticket, reporter_email=mail.sender)
        confirmation = await queue_confirmation(self.session, box, ticket)
        self._tickets.add_event(
            ticket,
            "created",
            {
                "confirmationSent": confirmation is not None,
                **({"followUpOf": format_number(follows.number)} if follows is not None else {}),
            },
        )
        return Taken("ticket", ticket_id=ticket.id, attachment_ids=stored.attachment_ids)

    async def _as_message(
        self, box: TicketMailbox, ticket: Ticket, mail: ParsedMail, source: bytes
    ) -> Taken:
        note = TicketNote(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            author_id=None,
            body=mail.text,
            visibility="public",
            mentions=[],
        )
        self.session.add(note)
        await self.session.flush()
        stored = await self._store_files(mail.files, ticket_note_id=note.id)
        await self._record(box, ticket.id, note.id, mail, source, stored)
        self._tickets.sender_answered(ticket)
        return Taken(
            "message", ticket_id=ticket.id, note_id=note.id, attachment_ids=stored.attachment_ids
        )

    async def _as_event(
        self, box: TicketMailbox, ticket: Ticket, mail: ParsedMail, source: bytes
    ) -> Taken:
        await self._record(box, ticket.id, None, mail, source, _Stored((), ()))
        self._tickets.add_event(
            ticket, "mail_auto", {"subject": mail.title, "from": mail.sender_name or mail.sender}
        )
        return Taken("event", ticket_id=ticket.id)

    async def _record(
        self,
        box: TicketMailbox,
        ticket_id: uuid.UUID,
        note_id: uuid.UUID | None,
        mail: ParsedMail,
        source: bytes,
        stored: _Stored,
    ) -> None:
        """Store the source and the identity row of a mail."""
        mail_id = uuid.uuid4()
        key = f"{SOURCE_PREFIX}{ticket_id}/{mail_id}.eml"
        await self.files.put_object(key, source, SOURCE_MIME)
        self.session.add(
            TicketMail(
                id=mail_id,
                mailbox_id=box.id,
                ticket_id=ticket_id,
                note_id=note_id,
                direction="in",
                message_id=mail.identity,
                from_address=mail.sender,
                from_name=mail.sender_name or None,
                cc=list(mail.cc),
                subject=mail.subject,
                source_key=key,
                source_size=len(source),
                source_scan=await self._scan(source),
                skipped=list(stored.skipped),
                automatic=mail.automatic,
            )
        )
        await self.session.flush()

    async def _scan(self, source: bytes) -> str | None:
        """Return the scan result of a source; None without a scanner or after a failure.

        A source without a result stays closed to a download. A failure of the scanner
        does not stop the import, because a large source can be above the limit of the
        scanner on each run.
        """
        if self.scanner is None:
            return None
        try:
            verdict = await self.scanner.scan(source)
        except ScannerError:
            logger.warning("scan of a mail source failed; the source stays closed")
            return None
        return "clean" if verdict.clean else (verdict.signature or "unknown")

    async def _store_files(
        self,
        files: tuple[MailFile, ...],
        *,
        ticket_id: uuid.UUID | None = None,
        ticket_note_id: uuid.UUID | None = None,
    ) -> _Stored:
        results = [
            await self._store_file(file, ticket_id=ticket_id, ticket_note_id=ticket_note_id)
            for file in files
        ]
        return _Stored(
            attachment_ids=tuple(r for r in results if isinstance(r, uuid.UUID)),
            skipped=tuple(r for r in results if isinstance(r, dict)),
        )

    async def _store_file(
        self,
        file: MailFile,
        *,
        ticket_id: uuid.UUID | None,
        ticket_note_id: uuid.UUID | None,
    ) -> uuid.UUID | dict[str, str | int]:
        """Store one file of a mail; return its id, or the entry of a left-out file."""
        if len(file.data) > self.files.max_bytes:
            return {"name": file.name, "size": len(file.data), "reason": "size"}
        try:
            mime, display_name = self.files.validate(file.name, file.data)
        except AppError:
            return {"name": file.name, "size": len(file.data), "reason": "type"}
        attachment_id = uuid.uuid4()
        owner = ticket_id or ticket_note_id
        key = f"tickets/{owner}/{attachment_id.hex}/{sanitize_storage_name(display_name)}"
        await self.files.put_object(key, file.data, mime)
        self.session.add(
            Attachment(
                id=attachment_id,
                ticket_id=ticket_id,
                ticket_note_id=ticket_note_id,
                filename=display_name,
                mime=mime,
                size=len(file.data),
                storage_key=key,
                scanned=False,
                scan_result=None,
            )
        )
        return attachment_id
