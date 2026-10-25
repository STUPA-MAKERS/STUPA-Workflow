"""Ticket tables: ``ticket``, ``ticket_note`` and ``ticket_event``.

``ticket.number`` comes from the sequence ``ticket_number_seq`` and reads as
``T-0001`` on the wire. A ticket has exactly one reporter: an account
(``reporter_principal_id``) or a bare e-mail address (``reporter_email``). The
anonymization clears both, so the check accepts no reporter once ``anonymized_at``
is set.

``closed_at`` is the retention clock. The status change into ``done`` or
``rejected`` sets it, a reopen clears it. The retention cron anonymizes a ticket
``tickets.retentionMonths`` after that moment.

A note is ``internal`` (the holders of ``ticket.manage`` only) or ``public`` (the
reporter account reads it too). Notes are soft-deleted (``deleted_at``). A note of the
reporter is ``public``; the anonymization clears its ``author_id``. Events are the timeline of
the status, the assignee and the kind. Both cascade with the ticket.

``ticket_sender_block`` holds the blocked senders: an account (``principal_id``) or a
normalized e-mail address (``email``, stripped and lowercase). A report of a blocked
sender is swallowed: it consumes a number and stores nothing (``hit_count``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin, UUIDPkMixin

#: The kinds of a ticket.
TICKET_KINDS: tuple[str, ...] = ("bug", "question", "idea")
#: The statuses of a ticket.
TICKET_STATUSES: tuple[str, ...] = ("new", "in_progress", "done", "rejected")
#: The statuses that close a ticket and start the retention clock.
CLOSED_STATUSES: frozenset[str] = frozenset({"done", "rejected"})
#: The visibilities of a note.
TICKET_NOTE_VISIBILITIES: tuple[str, ...] = ("internal", "public")
#: The kinds of a timeline event.
TICKET_EVENT_KINDS: tuple[str, ...] = ("created", "status", "assignee", "kind", "todo_done")

TICKET_NUMBER_SEQ = Sequence("ticket_number_seq")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Ticket(UUIDPkMixin, TimestampMixin, Base):
    """One reported ticket.

    Attributes:
        number: The running number from ``ticket_number_seq``.
        reporter_principal_id: The account of the reporter, else NULL.
        reporter_email: The e-mail of a reporter without a session, else NULL.
        duplicate_of_id: The ticket that this one duplicates (status ``rejected``).
        context: The technical context of the report (url, route, appVersion, ...).
        closed_at: Entry into ``done`` or ``rejected``; NULL while open.
        anonymized_at: Set by the retention cron or by an erasure.
    """

    __tablename__ = "ticket"

    number: Mapped[int] = mapped_column(
        Integer,
        TICKET_NUMBER_SEQ,
        server_default=TICKET_NUMBER_SEQ.next_value(),
        unique=True,
    )
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="new")
    reporter_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id"), nullable=True
    )
    reporter_email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principal.id"), nullable=True)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ticket.id", ondelete="SET NULL"), nullable=True
    )
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"kind IN ({_in(TICKET_KINDS)})", name="kind"),
        CheckConstraint(f"status IN ({_in(TICKET_STATUSES)})", name="status"),
        CheckConstraint(
            "anonymized_at IS NOT NULL OR num_nonnulls(reporter_principal_id, reporter_email) = 1",
            name="reporter",
        ),
        Index("ix_ticket_status", "status"),
        Index("ix_ticket_created_at", "created_at"),
        Index("ix_ticket_assignee", "assignee_id"),
    )


class TicketNote(UUIDPkMixin, Base):
    """A note on a ticket. Only its author edits or deletes it.

    ``author_id`` is NULL only for a note of the reporter on an anonymized ticket.
    """

    __tablename__ = "ticket_note"

    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ticket.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principal.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text, default="internal", server_default="internal")
    #: Principal ids (strings) of the mentioned holders of ``ticket.manage``. Only a team
    #: note mentions; the reporter never sees the list.
    mentions: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"visibility IN ({_in(TICKET_NOTE_VISIBILITIES)})", name="visibility"),
        Index("ix_ticket_note_ticket_id", "ticket_id"),
    )


class TicketEvent(UUIDPkMixin, Base):
    """One timeline event of a ticket. ``actor_id`` NULL means the system."""

    __tablename__ = "ticket_event"

    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ticket.id", ondelete="CASCADE"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principal.id"), nullable=True)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"kind IN ({_in(TICKET_EVENT_KINDS)})", name="kind"),
        Index("ix_ticket_event_ticket_id", "ticket_id"),
    )


class TicketSenderBlock(UUIDPkMixin, Base):
    """A blocked sender of reports: an account or an e-mail address.

    Exactly one of ``principal_id`` and ``email`` is set. ``email`` is stored
    stripped and lowercase. ``source_ticket_id`` is the ticket the block came from;
    it turns NULL when that ticket is deleted, an anonymization keeps it.

    Attributes:
        created_by: The holder of ``ticket.manage`` who blocked; NULL once deleted.
        hit_count: The reports swallowed since the block.
        last_hit_at: The moment of the last swallowed report.
    """

    __tablename__ = "ticket_sender_block"

    principal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), nullable=True
    )
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ticket.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    hit_count: Mapped[int] = mapped_column(Integer, server_default="0")
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("num_nonnulls(principal_id, email) = 1", name="target"),
        CheckConstraint("email IS NULL OR email = lower(email)", name="email_lower"),
        Index(
            "uq_ticket_sender_block_principal",
            "principal_id",
            unique=True,
            postgresql_where=text("principal_id IS NOT NULL"),
        ),
        Index(
            "uq_ticket_sender_block_email",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
    )
