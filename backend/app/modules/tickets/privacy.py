"""The mails of a ticket in an erasure and in the data export of a person.

An erasure anonymizes the tickets of an address in the platform, and the copies of the
mails stay on the mail server. So the erasure counts, for each Postfach, the mails of
the address that the platform imported or sent (§F/administration/privacy/002747). The
count is read before the erasure, because the anonymization removes the addresses of
the mail rows.

The data export holds each ticket whose sender or ``Cc`` address is the address of the
person, with its public messages (§F/administration/privacy/002748).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal
from app.modules.files.models import Attachment
from app.modules.tickets.models import Ticket, TicketMail, TicketMailbox, TicketNote
from app.modules.tickets.numbers import format_number


def _wrote(email: str) -> ColumnElement[bool]:
    """Match a mail whose sender or ``Cc`` address is ``email``."""
    return or_(TicketMail.from_address == email, TicketMail.cc.contains([email]))


async def mail_counts_of(session: AsyncSession, email: str | None) -> list[dict[str, Any]]:
    """Return, for each Postfach, the count of the mails from or to ``email``.

    A row with ``mailbox`` None counts the mails of a Postfach that is removed.
    """
    if not email:
        return []
    address = email.lower()
    rows = await session.execute(
        select(TicketMailbox.address, func.count(TicketMail.id))
        .select_from(TicketMail)
        .outerjoin(TicketMailbox, TicketMailbox.id == TicketMail.mailbox_id)
        .where(or_(_wrote(address), TicketMail.to_addresses.contains([address])))
        .group_by(TicketMailbox.address)
        .order_by(TicketMailbox.address)
    )
    return [{"mailbox": mailbox, "count": int(count)} for mailbox, count in rows.all()]


async def mail_counts_of_principal(
    session: AsyncSession, principal_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Return the mail counts of the address of one account."""
    email = await session.scalar(select(Principal.email).where(Principal.id == principal_id))
    return await mail_counts_of(session, email)


async def mail_ticket_ids_of(session: AsyncSession, email: str) -> Sequence[uuid.UUID]:
    """Return the tickets with an imported mail whose sender or ``Cc`` is ``email``."""
    rows = await session.scalars(
        select(TicketMail.ticket_id)
        .where(TicketMail.direction == "in", _wrote(email.lower()))
        .distinct()
    )
    return rows.all()


async def public_messages_of(
    session: AsyncSession, ticket_ids: Sequence[uuid.UUID], *, skip: Sequence[uuid.UUID] = ()
) -> list[dict[str, Any]]:
    """Return the public messages of the tickets with the names of their files.

    An internal message is never part of the answer. ``skip`` names the messages that
    the export already holds.
    """
    if not ticket_ids:
        return []
    rows = (
        await session.execute(
            select(TicketNote, Ticket.number)
            .join(Ticket, Ticket.id == TicketNote.ticket_id)
            .where(
                TicketNote.ticket_id.in_(ticket_ids),
                TicketNote.visibility == "public",
                TicketNote.deleted_at.is_(None),
                TicketNote.id.not_in(skip) if skip else TicketNote.id.is_not(None),
            )
            .order_by(Ticket.number, TicketNote.created_at, TicketNote.id)
        )
    ).all()
    files = (
        await session.execute(
            select(Attachment.ticket_note_id, Attachment.filename)
            .where(Attachment.ticket_note_id.in_([note.id for note, _ in rows]))
            .order_by(Attachment.created_at, Attachment.id)
        )
    ).all()
    return [
        {
            "ticketNumber": format_number(number),
            "visibility": note.visibility,
            "createdAt": note.created_at,
            "deletedAt": note.deleted_at,
            "body": note.body,
            "attachments": [name for owner, name in files if owner == note.id],
        }
        for note, number in rows
    ]
