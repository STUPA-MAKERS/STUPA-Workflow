"""Ticket tables: ``ticket``, ``ticket_note`` and ``ticket_event``.

``ticket.number`` holds eight random characters (``numbers.draw_number``) and reads as
``T-7K3QX9MD`` on the wire. The service draws again when a ticket has the number. A
ticket has exactly one reporter: an account
(``reporter_principal_id``) or a bare e-mail address (``reporter_email``). The
anonymization clears both, so the check accepts no reporter once ``anonymized_at``
is set.

``closed_at`` is the retention clock. The status change into ``done`` or
``rejected`` sets it, a reopen clears it. ``waiting`` (Wartet auf Antwort) is an open
status and never starts the clock. ``source`` names the way the ticket came:
``help`` (the help menu), ``mail`` or ``team`` (a person of the team wrote it by hand).
The body of a ``team`` ticket is the note of the team, so the view of the reporter
leaves it out. ``follow_up_of_id`` names the closed ticket that a late message of the
sender answered (``REOPEN_DAYS``). The retention cron anonymizes a ticket
``tickets.retentionMonths`` after that moment.

A note is ``internal`` (the holders of ``ticket.manage`` only) or ``public`` (the
reporter account reads it too). Notes are soft-deleted (``deleted_at``). A note of the
reporter is ``public``; the anonymization clears its ``author_id``. Events are the timeline of
the status, the assignee and the kind. Both cascade with the ticket.

A ticket belongs to exactly one Bereich (``ticket_area``). The Bereich ``Plattform`` is
built in and has the fixed id ``PLATFORM_AREA_ID``, so the reports of the help menu have
a place on every installation. A Bereich belongs to one Gremium or to none; the Gremium
decides who works in it (``access.py``). A ticket of ``Plattform`` has a ``kind``, the
fixed Kategorien of that Bereich. A ticket of a different Bereich has no kind and at most
one Kategorie of its Bereich (``ticket_category``).

``ticket_sender_block`` holds the blocked senders: an account (``principal_id``) or a
normalized e-mail address (``email``, stripped and lowercase). A report of a blocked
sender is swallowed: it answers a number and stores nothing (``hit_count``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin, UUIDPkMixin
from app.modules.tickets.numbers import draw_number

#: The kinds of a ticket.
TICKET_KINDS: tuple[str, ...] = ("bug", "question", "idea", "barrier")
#: The statuses of a ticket.
TICKET_STATUSES: tuple[str, ...] = ("new", "in_progress", "waiting", "done", "rejected")
#: The statuses that close a ticket and start the retention clock.
CLOSED_STATUSES: frozenset[str] = frozenset({"done", "rejected"})
#: The sources of a ticket: the help menu, a mail, or a person of the team.
TICKET_SOURCES: tuple[str, ...] = ("help", "mail", "team")
#: The days after the close in which a message of the sender opens the ticket again.
REOPEN_DAYS = 14
#: The visibilities of a note.
TICKET_NOTE_VISIBILITIES: tuple[str, ...] = ("internal", "public")
#: The kinds of a timeline event.
TICKET_EVENT_KINDS: tuple[str, ...] = (
    "created",
    "status",
    "assignee",
    "kind",
    "todo_done",
    "category",
    "area",
)
#: The id of the built-in Bereich ``Plattform``. The migration creates the row.
PLATFORM_AREA_ID = uuid.UUID("7a11e700-0000-4000-8000-000000000001")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class TicketArea(UUIDPkMixin, TimestampMixin, Base):
    """A Bereich: the unit that separates the tickets, the rights and the settings of a team.

    Attributes:
        name: The name, unique on the platform.
        gremium_id: The Gremium that owns the Bereich, else NULL. The Bereich stays
            without a Gremium when the Gremium is deleted.
        platform: True only for the built-in Bereich ``Plattform``.
        notify_new: Mail each new ticket to the team of the Bereich.
        in_app: A signed-in person can choose the Bereich in the ticket dialog of the
            help menu. ``Plattform`` is reachable without the switch.
    """

    __tablename__ = "ticket_area"

    name: Mapped[str] = mapped_column(Text, unique=True)
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    notify_new: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    in_app: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    __table_args__ = (
        CheckConstraint("NOT platform OR gremium_id IS NULL", name="platform_without_gremium"),
        Index(
            "uq_ticket_area_one_platform",
            "platform",
            unique=True,
            postgresql_where=text("platform"),
        ),
        Index("ix_ticket_area_gremium_id", "gremium_id"),
    )


class TicketMailbox(UUIDPkMixin, TimestampMixin, Base):
    """The Postfach of a Bereich: one address with an IMAP and an SMTP account.

    A Bereich has at most one Postfach (§F/integrations/ticket-mail/002720), and the
    Postfach goes with its Bereich. No read of the API returns a password
    (§NF/security/network/002746).

    Attributes:
        area_id: The Bereich, unique.
        address: The e-mail address of the Postfach.
        done_folder: The IMAP folder that takes each imported mail.
        enabled: The switch. While it is off, the platform opens no connection.
        uid_validity: The ``UIDVALIDITY`` of the inbox at the last fetch.
        last_uid: The highest UID of the inbox that the fetch took.
        failures: The failed fetch runs in sequence.
        last_error: The short cause code of the newest failure, never a text of an
            exception.
        fetched_at: The moment of the last fetch without a failure.
    """

    __tablename__ = "ticket_mailbox"

    area_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ticket_area.id", ondelete="CASCADE"), unique=True
    )
    address: Mapped[str] = mapped_column(CITEXT)
    imap_host: Mapped[str] = mapped_column(Text)
    imap_port: Mapped[int] = mapped_column(Integer)
    imap_user: Mapped[str] = mapped_column(Text)
    imap_password: Mapped[str] = mapped_column(Text)
    smtp_host: Mapped[str] = mapped_column(Text)
    smtp_port: Mapped[int] = mapped_column(Integer)
    smtp_user: Mapped[str] = mapped_column(Text)
    smtp_password: Mapped[str] = mapped_column(Text)
    done_folder: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    uid_validity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_uid: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    failures: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TicketCategory(UUIDPkMixin, Base):
    """A Kategorie of a Bereich. ``position`` orders the list of the Bereich.

    The unique name of a Bereich is checked at the commit, so one save can swap the
    names of two Kategorien.
    """

    __tablename__ = "ticket_category"

    area_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ticket_area.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    __table_args__ = (
        UniqueConstraint(
            "area_id",
            "name",
            name="uq_ticket_category_area_name",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_ticket_category_area_id", "area_id"),
    )


class Ticket(UUIDPkMixin, TimestampMixin, Base):
    """One reported ticket.

    Attributes:
        area_id: The Bereich of the ticket; a ticket without one cannot exist.
        category_id: The Kategorie, of the same Bereich, else NULL.
        number: The eight random characters of the number, unique on the platform.
        reporter_principal_id: The account of the reporter, else NULL.
        reporter_email: The e-mail of a reporter without a session, else NULL.
        duplicate_of_id: The ticket that this one duplicates (status ``rejected``).
        follow_up_of_id: The closed ticket that this one follows, else NULL.
        source: ``help``, ``mail`` or ``team``.
        context: The technical context of the report (url, route, appVersion, ...).
        closed_at: Entry into ``done`` or ``rejected``; NULL while open.
        anonymized_at: Set by the retention cron or by an erasure.
    """

    __tablename__ = "ticket"

    number: Mapped[str] = mapped_column(Text, default=draw_number, unique=True)
    area_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ticket_area.id"), default=PLATFORM_AREA_ID
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ticket_category.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    follow_up_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ticket.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(Text, default="help", server_default="help")
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"kind IN ({_in(TICKET_KINDS)})", name="kind"),
        CheckConstraint(f"status IN ({_in(TICKET_STATUSES)})", name="status"),
        CheckConstraint(f"source IN ({_in(TICKET_SOURCES)})", name="source"),
        CheckConstraint(
            "anonymized_at IS NOT NULL OR num_nonnulls(reporter_principal_id, reporter_email) = 1",
            name="reporter",
        ),
        Index("ix_ticket_status", "status"),
        Index("ix_ticket_created_at", "created_at"),
        Index("ix_ticket_assignee", "assignee_id"),
        Index("ix_ticket_area_id", "area_id"),
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
