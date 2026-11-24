"""Support of the integration tests of the ticket mails: a scripted inbox and a Postfach.

``Scripted`` stands for the IMAP inbox, so no test opens a socket. ``Stack`` is one
Bereich with a Postfach and the context of the worker jobs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.files.scanner import ScanVerdict
from app.modules.tickets.mail_client import MailAccount, MailError
from app.modules.tickets.models import Ticket, TicketArea, TicketMail, TicketMailbox, TicketNote
from tests._support.files_fakes import FakeStorage
from worker.ticket_mail import fetch_ticket_mails, send_ticket_mails

HOST = "mail.stupa.example"
ADDRESS = "buero@stupa.example"
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


@dataclass
class Scripted:
    """A scripted inbox: the mails by UID, and the moves that the job asked for."""

    mails: dict[int, bytes] = field(default_factory=dict)
    moved: list[tuple[int, str]] = field(default_factory=list)
    opened: list[MailAccount] = field(default_factory=list)
    uid_validity: int = 1
    fail: str | None = None

    def open(self, account: MailAccount) -> Scripted:
        self.opened.append(account)
        if self.fail is not None:
            raise MailError(self.fail)
        return self

    def put(self, source: bytes) -> int:
        uid = max([0, *self.mails, *(uid for uid, _folder in self.moved)]) + 1
        self.mails[uid] = source
        return uid

    def uids_after(self, last_uid: int) -> list[int]:
        return sorted(uid for uid in self.mails if uid > last_uid)

    def size(self, uid: int) -> int:
        return len(self.mails[uid])

    def fetch(self, uid: int) -> bytes:
        return self.mails[uid]

    def move(self, uid: int, folder: str) -> None:
        del self.mails[uid]
        self.moved.append((uid, folder))

    def close(self) -> None:
        return None


class CleanScanner:
    async def scan(self, _data: bytes) -> ScanVerdict:
        return ScanVerdict(clean=True)


@dataclass
class Stack:
    """One Bereich with a Postfach, its scripted inbox and the context of the job."""

    maker: async_sessionmaker[AsyncSession]
    area_id: uuid.UUID
    box_id: uuid.UUID
    inbox: Scripted
    storage: FakeStorage
    ctx: dict[str, Any]

    sent: list[tuple[MailAccount, EmailMessage]] = field(default_factory=list)
    send_fails: str | None = None

    async def run(self) -> int:
        return await fetch_ticket_mails(self.ctx)

    def send(self, account: MailAccount, message: EmailMessage) -> None:
        """Stand for the SMTP send: keep the message, or fail with ``send_fails``."""
        if self.send_fails is not None:
            raise MailError(self.send_fails)
        self.sent.append((account, message))

    async def deliver(self, now: datetime | None = None) -> int:
        return await send_ticket_mails(self.ctx, now)

    async def mails(self) -> list[TicketMail]:
        async with self.maker() as session:
            return list(
                (
                    await session.scalars(
                        select(TicketMail).order_by(TicketMail.created_at, TicketMail.id)
                    )
                ).all()
            )

    async def box(self) -> TicketMailbox:
        async with self.maker() as session:
            row = await session.get(TicketMailbox, self.box_id)
            assert row is not None
            return row

    async def tickets(self) -> list[Ticket]:
        async with self.maker() as session:
            return list(
                (await session.scalars(select(Ticket).order_by(Ticket.created_at, Ticket.id))).all()
            )

    async def notes(self, ticket_id: uuid.UUID) -> list[TicketNote]:
        async with self.maker() as session:
            return list(
                (
                    await session.scalars(
                        select(TicketNote)
                        .where(TicketNote.ticket_id == ticket_id)
                        .order_by(TicketNote.created_at, TicketNote.id)
                    )
                ).all()
            )


async def make_box(
    maker: async_sessionmaker[AsyncSession], name: str, *, enabled: bool = True
) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as session:
        area = TicketArea(id=uuid.uuid4(), name=name, notify_new=False)
        session.add(area)
        await session.flush()
        box = TicketMailbox(
            id=uuid.uuid4(),
            area_id=area.id,
            address=ADDRESS,
            imap_host=HOST,
            imap_port=993,
            imap_user="buero",
            imap_password="geheim-imap",
            smtp_host=HOST,
            smtp_port=465,
            smtp_user="buero",
            smtp_password="geheim-smtp",
            done_folder="Erledigt",
            enabled=enabled,
        )
        session.add(box)
        await session.commit()
        return area.id, box.id


def raw_mail(
    *,
    sender: str = "Anna Beispiel <anna@example.org>",
    subject: str | None = "Raumanfrage",
    body: str = "Ich brauche einen Raum.",
    message_id: str | None = None,
    **headers: str,
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ADDRESS
    if subject is not None:
        message["Subject"] = subject
    if message_id is not None:
        message["Message-ID"] = message_id
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    message.set_content(body)
    return bytes(message)
