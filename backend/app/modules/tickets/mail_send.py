"""Send the mails of a ticket through the SMTP account of the Postfach of its Bereich.

A public message of the team on a mail ticket goes out as a mail
(§F/integrations/ticket-mail/002733). A mail ticket is a ticket from a mail or a ticket
by hand for an address: its sender has no account. ``queue_answer`` stores the mail with
the state ``sending`` in the transaction of the message. ``MailSender.send_due`` runs in
the worker and sends each waiting mail (§F/integrations/ticket-mail/002737).

A sent mail has its own ``Message-ID``, names the last mail of the ticket in
``In-Reply-To`` and each mail of the ticket in ``References``, and has the title of the
ticket with the number as its subject (§F/integrations/ticket-mail/002734). ``From`` is
the address of the Postfach with the name of the Bereich, and the text ends with the
signature of the Postfach (§F/integrations/ticket-mail/002736).

A failed send counts on the mail. The wait doubles after each failure, and the eighth
failure ends in the state ``failed``. A file of the message without a clean scan result
is a failure with the cause ``files_not_scanned``, so no unchecked file leaves the
platform.

The confirmation of a new ticket (§F/integrations/ticket-mail/002738) is a sent mail
without a message and with the mark ``automatic``. It carries ``Auto-Submitted:
auto-replied``. Its subject and its text name only the number, never a value of the
incoming mail (§F/integrations/ticket-mail/002814), and a Postfach sends at most
``CONFIRM_CAP`` of them an hour over all addresses (§F/integrations/ticket-mail/002815),
because the ``From`` of a mail is not checked: else a stranger could send a text of their
own from the address of the Bereich to any address.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, formataddr

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.files.models import Attachment
from app.modules.files.storage import ObjectStorage
from app.modules.tickets import mail_client
from app.modules.tickets.mail_client import MailAccount, MailError
from app.modules.tickets.mailbox import smtp_account
from app.modules.tickets.models import (
    PLATFORM_AREA_ID,
    Ticket,
    TicketArea,
    TicketMail,
    TicketMailbox,
    TicketNote,
)
from app.modules.tickets.numbers import NUMBER_ALPHABET, NUMBER_LENGTH, format_number
from app.settings import Settings
from app.shared.errors import ConflictError, ValidationProblem
from app.shared.ssrf import host_allowed

logger = logging.getLogger("app.tickets")

#: The problem code of a public message while the Postfach is off or missing.
MAILBOX_OFF = "mailbox_off"
#: The problem code of a message to nobody.
NO_RECIPIENT = "mail_without_recipient"
#: The problem code of a second send of a mail that did not fail.
MAIL_NOT_FAILED = "mail_not_failed"
#: The sends of one mail before the state ``failed``.
MAX_ATTEMPTS = 8
#: The wait after the first failed send. It doubles after each failure.
FIRST_WAIT = timedelta(minutes=1)
#: The time in which one address gets at most one confirmation.
CONFIRM_WINDOW = timedelta(hours=1)
#: The confirmations that one Postfach sends at most in ``CONFIRM_WINDOW``.
CONFIRM_CAP = 30
#: The subject of a confirmation, with the number of the ticket at the end.
CONFIRM_SUBJECT = "Deine Nachricht ist eingegangen [{number}]"
#: The placeholder of the writer in a signature.
NAME_PLACEHOLDER = "{name}"
#: The cause code of a file without a clean scan result.
FILES_NOT_SCANNED = "files_not_scanned"
#: The cause code of a host outside the allowlist.
HOST_NOT_ALLOWED = "mail_host_not_allowed"
#: The cause code of a failure that is no failure of the mail server.
SEND_FAILED = "send_failed"
#: The text of the confirmation of a new ticket.
CONFIRM_TEXT = (
    "Hallo,\n\n"
    "wir haben deine Nachricht erhalten. Sie hat die Nummer {number}.\n"
    "Lass die Nummer bitte im Betreff stehen, wenn du auf diese Mail antwortest."
)

_NUMBER_TAG = re.compile(rf"\s*\[T-[{NUMBER_ALPHABET}]{{{NUMBER_LENGTH}}}\]")
_REPLY_MARK = re.compile(r"^\s*((re|aw|fwd?|wg)\s*:\s*)+", re.IGNORECASE)

#: Sends one message through an SMTP account; blocks, so it runs in a thread.
Send = Callable[[MailAccount, EmailMessage], None]


@dataclass(frozen=True, slots=True)
class Recipients:
    """The addresses of a mail, each stripped and lowercase."""

    to: tuple[str, ...]
    cc: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MailFileOut:
    """One file of a sent mail."""

    name: str
    mime: str
    data: bytes


@dataclass(frozen=True, slots=True)
class Thread:
    """The mails of a ticket before a new mail: the last identity and all of them."""

    last: str | None
    all: tuple[str, ...]


def is_mail_ticket(ticket: Ticket) -> bool:
    """Tell if the sender of the ticket is an address that the team answers by mail."""
    return (
        ticket.reporter_principal_id is None
        and bool(ticket.reporter_email)
        and ticket.source in {"mail", "team"}
    )


def _clean(addresses: Iterable[str | None]) -> tuple[str, ...]:
    found = [str(entry).strip().lower() for entry in addresses if entry]
    return tuple(dict.fromkeys(entry for entry in found if "@" in entry))


def thread_recipients(ticket: Ticket, mails: Sequence[TicketMail], own: str) -> Recipients:
    """Return the sender in ``to`` and each other address of the thread in ``cc``.

    The address of the Postfach is in neither list
    (§F/integrations/ticket-mail/002735).
    """
    mine = own.strip().lower()
    to = _clean([ticket.reporter_email])
    others = _clean(
        entry
        for mail in mails
        for entry in (
            *(mail.cc or []),
            *(mail.to_addresses or []),
            mail.from_address if mail.direction == "in" else None,
        )
    )
    return Recipients(to=to, cc=tuple(a for a in others if a != mine and a not in to))


def chosen_recipients(
    default: Recipients, to: Sequence[str] | None, cc: Sequence[str] | None, own: str
) -> Recipients:
    """Return the addresses that the writer chose, else the addresses of the thread."""
    mine = own.strip().lower()
    first = tuple(a for a in _clean(to) if a != mine) if to is not None else default.to
    second = _clean(cc) if cc is not None else default.cc
    return Recipients(to=first, cc=tuple(a for a in second if a != mine and a not in first))


def subject_of(ticket: Ticket, *, answers: bool) -> str:
    """Return the title with the number at the end, and ``Re:`` in front of an answer."""
    title = _REPLY_MARK.sub("", _NUMBER_TAG.sub("", ticket.title or "")).strip()
    return f"{'Re: ' if answers else ''}{title} [{format_number(ticket.number)}]".strip()


def new_message_id(address: str) -> str:
    """Return a new ``Message-ID`` in the domain of the Postfach."""
    domain = address.rpartition("@")[2].strip().lower() or "localhost"
    return f"<{uuid.uuid4().hex}@{domain}>"


def signed(text: str, signature: str, writer: str) -> str:
    """Return the text with the signature; ``{name}`` becomes the writer."""
    end = signature.replace(NAME_PLACEHOLDER, writer).strip()
    return f"{text.strip()}\n\n{end}".strip() if end else text.strip()


def wait_after(attempts: int) -> timedelta:
    """Return the wait after the given count of failed sends."""
    return FIRST_WAIT * (2 ** max(attempts - 1, 0))


def build_message(
    mail: TicketMail,
    *,
    area_name: str,
    text: str,
    thread: Thread,
    files: Sequence[MailFileOut] = (),
    now: datetime | None = None,
) -> EmailMessage:
    """Build the mail of a stored row. The function opens no connection."""
    headers = (
        ("From", formataddr((area_name, str(mail.from_address or "")))),
        ("To", ", ".join(str(a) for a in mail.to_addresses or [])),
        ("Cc", ", ".join(str(a) for a in mail.cc or [])),
        ("Subject", mail.subject or ""),
        ("Date", format_datetime(now or datetime.now(UTC))),
        ("Message-ID", mail.message_id),
        ("In-Reply-To", thread.last or ""),
        ("References", " ".join(thread.all)),
        ("Auto-Submitted", "auto-replied" if mail.automatic else ""),
    )
    message = EmailMessage()
    _fill(message, [(name, value) for name, value in headers if value], text, files)
    return message


def _fill(
    message: EmailMessage,
    headers: Sequence[tuple[str, str]],
    text: str,
    files: Sequence[MailFileOut],
) -> None:
    """Write the headers, the text and the files into an empty message."""
    for name, value in headers:
        message.add_header(name, value)
    message.set_content(text)
    for file in files:
        maintype, _, subtype = file.mime.partition("/")
        message.add_attachment(
            file.data,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=file.name,
        )


def send_smtp(account: MailAccount, message: EmailMessage) -> None:
    """Send one message through the SMTP account.

    Raises:
        MailError: A connection cause of ``open_smtp``, or ``send_refused`` when the
            server does not take the mail.
    """
    conn = mail_client.open_smtp(account)
    try:
        conn.send_message(message)
    except Exception:
        raise MailError("send_refused") from None
    finally:
        with contextlib.suppress(Exception):
            conn.quit()


async def mailbox_of(session: AsyncSession, ticket: Ticket) -> TicketMailbox | None:
    """Return the Postfach of the Bereich of the ticket, else None."""
    return await session.scalar(
        select(TicketMailbox).where(TicketMailbox.area_id == (ticket.area_id or PLATFORM_AREA_ID))
    )


async def mails_of(session: AsyncSession, ticket_id: uuid.UUID) -> Sequence[TicketMail]:
    """Return the mails of a ticket, oldest first."""
    return (
        await session.scalars(
            select(TicketMail)
            .where(TicketMail.ticket_id == ticket_id)
            .order_by(TicketMail.created_at, TicketMail.id)
        )
    ).all()


async def queue_answer(
    session: AsyncSession,
    ticket: Ticket,
    note_id: uuid.UUID,
    *,
    to: Sequence[str] | None = None,
    cc: Sequence[str] | None = None,
) -> TicketMail:
    """Store the mail of a public message with the state ``sending``, without a commit.

    Raises:
        ConflictError: The Bereich has no Postfach, or its switch is off (HTTP 409,
            ``mailbox_off``, §F/integrations/ticket-mail/002722).
        ValidationProblem: No address is left in ``to`` (HTTP 422,
            ``mail_without_recipient``).
    """
    box = await mailbox_of(session, ticket)
    if box is None or not box.enabled:
        raise ConflictError("The Postfach of the Bereich is off.", code=MAILBOX_OFF)
    mails = await mails_of(session, ticket.id)
    own = str(box.address)
    people = chosen_recipients(thread_recipients(ticket, mails, own), to, cc, own)
    if not people.to:
        raise ValidationProblem(
            "The mail names no recipient.",
            code=NO_RECIPIENT,
            errors=[{"field": "to", "msg": "at least one address"}],
        )
    row = TicketMail(
        id=uuid.uuid4(),
        mailbox_id=box.id,
        ticket_id=ticket.id,
        note_id=note_id,
        direction="out",
        message_id=new_message_id(own),
        from_address=own.strip().lower(),
        to_addresses=list(people.to),
        cc=list(people.cc),
        subject=subject_of(ticket, answers=any(m.direction == "in" for m in mails)),
        state="sending",
        next_try_at=datetime.now(UTC),
    )
    session.add(row)
    return row


async def queue_confirmation(
    session: AsyncSession, box: TicketMailbox, ticket: Ticket, *, now: datetime | None = None
) -> TicketMail | None:
    """Store the confirmation of a new ticket from a mail, without a commit.

    Returns:
        The stored mail, or None while the switch is off, when the Postfach sent
        ``CONFIRM_CAP`` confirmations in the last hour, or when the address got a
        confirmation in the last hour.
    """
    address = (ticket.reporter_email or "").strip().lower()
    if not box.confirm or not box.enabled or not address:
        return None
    moment = now or datetime.now(UTC)
    sent = await session.scalar(
        select(func.count())
        .select_from(TicketMail)
        .where(
            TicketMail.mailbox_id == box.id,
            TicketMail.direction == "out",
            TicketMail.automatic.is_(True),
            TicketMail.created_at > moment - CONFIRM_WINDOW,
        )
    )
    if (sent or 0) >= CONFIRM_CAP:
        return None
    recent = await session.scalar(
        select(TicketMail.id)
        .where(
            TicketMail.direction == "out",
            TicketMail.automatic.is_(True),
            TicketMail.to_addresses.contains([address]),
            TicketMail.created_at > moment - CONFIRM_WINDOW,
        )
        .limit(1)
    )
    if recent is not None:
        return None
    own = str(box.address)
    row = TicketMail(
        id=uuid.uuid4(),
        mailbox_id=box.id,
        ticket_id=ticket.id,
        note_id=None,
        direction="out",
        message_id=new_message_id(own),
        from_address=own.strip().lower(),
        to_addresses=[address],
        cc=[],
        subject=CONFIRM_SUBJECT.format(number=format_number(ticket.number)),
        automatic=True,
        state="sending",
        next_try_at=moment,
        created_at=moment,
    )
    session.add(row)
    return row


def send_again(mail: TicketMail, *, now: datetime | None = None) -> None:
    """Start the send of a failed mail again.

    Raises:
        ConflictError: The mail is no sent mail in the state ``failed`` (HTTP 409,
            ``mail_not_failed``).
    """
    if mail.direction != "out" or mail.state != "failed":
        raise ConflictError("The mail did not fail.", code=MAIL_NOT_FAILED)
    for name, value in (
        ("state", "sending"),
        ("attempts", 0),
        ("send_error", None),
        ("next_try_at", now or datetime.now(UTC)),
    ):
        setattr(mail, name, value)


@dataclass(frozen=True, slots=True)
class MailSender:
    """Send the waiting mails, bound to a session, the storage and the settings."""

    session: AsyncSession
    storage: ObjectStorage | None
    settings: Settings
    send: Send = send_smtp

    async def send_next(self, now: datetime | None = None) -> bool | None:
        """Send the next mail whose time has come, without a commit.

        The row stays locked until the commit of the caller, and a second worker skips
        a locked mail (``SKIP LOCKED``), so no mail goes out twice.

        Returns:
            True for a sent mail, False for a failed send, None when no mail waits.
        """
        moment = now or datetime.now(UTC)
        mail = await self.session.scalar(
            select(TicketMail)
            .where(
                TicketMail.direction == "out",
                TicketMail.state == "sending",
                TicketMail.next_try_at <= moment,
            )
            .order_by(TicketMail.next_try_at, TicketMail.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if mail is None:
            return None
        cause = await self._try(mail, moment)
        self._store(mail, cause, moment)
        await self.session.flush()
        return cause is None

    async def _try(self, mail: TicketMail, moment: datetime) -> str | None:
        """Send one mail and return the cause code of a failure, else None."""
        try:
            await self._deliver(mail, moment)
        except MailError as exc:
            return exc.code
        except Exception:
            logger.exception("ticket mail send crashed (mail=%s)", mail.id)
            return SEND_FAILED
        return None

    def _store(self, mail: TicketMail, cause: str | None, moment: datetime) -> None:
        attempts = (mail.attempts or 0) + 1
        values: dict[str, object] = (
            {"state": "sent", "send_error": None, "next_try_at": None}
            if cause is None
            else {
                "state": "failed" if attempts >= MAX_ATTEMPTS else "sending",
                "attempts": attempts,
                "send_error": cause,
                "next_try_at": moment + wait_after(attempts),
            }
        )
        for name, value in values.items():
            setattr(mail, name, value)

    async def _deliver(self, mail: TicketMail, moment: datetime) -> None:
        box = (
            await self.session.get(TicketMailbox, mail.mailbox_id)
            if mail.mailbox_id is not None
            else None
        )
        if box is None or not box.enabled:
            raise MailError(MAILBOX_OFF)
        account = smtp_account(box)
        if not host_allowed(account.host, account.port, self.settings.ticket_mail_host_allowlist):
            raise MailError(HOST_NOT_ALLOWED)
        ticket = await self.session.get(Ticket, mail.ticket_id)
        area = await self.session.get(TicketArea, box.area_id)
        if ticket is None or area is None:
            raise MailError(SEND_FAILED)
        note = await self.session.get(TicketNote, mail.note_id) if mail.note_id else None
        message = build_message(
            mail,
            area_name=area.name,
            text=signed(
                await self._text(ticket, note),
                box.signature or "",
                await _writer(self.session, note),
            ),
            thread=await self._thread(mail),
            files=await self._files(note),
            now=moment,
        )
        await asyncio.to_thread(self.send, account, message)

    async def _text(self, ticket: Ticket, note: TicketNote | None) -> str:
        if note is not None:
            return note.body or ""
        return CONFIRM_TEXT.format(number=format_number(ticket.number))

    async def _thread(self, mail: TicketMail) -> Thread:
        """Return the identities of the older mails of the ticket with a ``Message-ID``."""
        older = [
            other.message_id
            for other in await mails_of(self.session, mail.ticket_id)
            if other.id != mail.id
            and other.created_at <= mail.created_at
            and other.message_id.startswith("<")
            and (other.direction == "in" or other.state == "sent")
        ]
        return Thread(last=older[-1] if older else None, all=tuple(older))

    async def _files(self, note: TicketNote | None) -> tuple[MailFileOut, ...]:
        """Read the files of the message; each needs a clean scan result."""
        if note is None:
            return ()
        rows = (
            await self.session.scalars(
                select(Attachment)
                .where(Attachment.ticket_note_id == note.id)
                .order_by(Attachment.created_at, Attachment.id)
            )
        ).all()
        if not rows:
            return ()
        if self.storage is None or any(
            not row.scanned or row.scan_result != "clean" or row.storage_key is None for row in rows
        ):
            raise MailError(FILES_NOT_SCANNED)
        return tuple(
            [
                MailFileOut(row.filename, row.mime, await _read(self.storage, str(row.storage_key)))
                for row in rows
            ]
        )


async def _read(storage: ObjectStorage, key: str) -> bytes:
    return await storage.get(key)


async def _writer(session: AsyncSession, note: TicketNote | None) -> str:
    """Return the display name of the writer of a message, else an empty text."""
    if note is None or note.author_id is None:
        return ""
    name = await session.scalar(
        select(PrincipalRow.display_name).where(PrincipalRow.id == note.author_id)
    )
    return name or ""
