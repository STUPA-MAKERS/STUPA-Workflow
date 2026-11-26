"""To-do tables: boards, columns, cards and everything that hangs on a card.

A board has one of four kinds, and the kind decides its owner column:

* ``team`` — ``team_id``; one board per team (``uq_todo_board_team``, spec 003067). The
  board of an inherent team is the board of its Gremium; the board names the team and
  never the Gremium.
* ``personal`` — ``owner_id``; one board per account (``uq_todo_board_owner``).
* ``permission`` — ``permission``; the holders of that global permission (spec 003073).
* ``free`` — no owner column; its members are its entries only (spec 001060).

``ck_todo_board_owner`` keeps exactly the owner column of the kind set.

``todo_board_entry`` holds the member entries of a free board and the extra entries of a
team board (specs 001060, 001077, 003068): exactly one of ``team_id`` and
``principal_id``, with the role ``read``, ``edit`` or ``manage``. The own team of a
team board is no row, it is a fixed member (spec 003067).

A board has exactly one done column (partial unique index ``uq_todo_column_done``).
A card in the done column carries ``completed_at``; a move out clears it. A card
sorts inside its column by ``rank``, a lexorank string with the collation ``C``, so
a move writes one row only (``lexorank.py``). ``version`` guards the content edits
(title, description, due date) against a lost update.

``link`` connects two elements of any two kinds (specs 001400-001402): an application,
a meeting, an agenda item, a vote, a Termin (``calendar_appointment``), a gremium, an
invoice, a booking (``budget_expense``), a Bestellung, an Event, a cost centre (``budget``),
a ticket, a card or a Paperless document.
A link has no direction. Its two ends are stored in a fixed order, ``(a_kind, a_id)``
before ``(b_kind, b_id)`` by byte order (``Link.between``), so the unique index holds one
row per pair. An end has no foreign key, because it points into one of eleven tables:
an ``AFTER DELETE`` trigger on each of them (``link_drop_ends``, migration
``c4d1e2f3a5b6``) deletes the links of a deleted element.
``todo_event`` is the timeline of a card; there is no audit entry for to-dos.

``due_reminded_on`` is the due date that the ``todo_due`` reminder went out for. A
changed due date gets a new reminder.

A card holds no event data: an Event is an element of its own (``app.modules.events``,
F/collaboration/events/003022). ``todo_event_series`` holds the series (``Reihe``) of the
Events. A series has a name that is unique in the platform and belongs to no board.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin, UUIDPkMixin

#: The kinds of a board.
BOARD_KINDS: tuple[str, ...] = ("team", "personal", "permission", "free")
#: The roles of a member entry, from the lowest to the highest (spec 001062).
ENTRY_ROLES: tuple[str, ...] = ("read", "edit", "manage")
#: The colors of a label (a fixed palette of the frontend).
LABEL_COLORS: tuple[str, ...] = ("green", "blue", "violet", "amber", "red", "gray")
#: The kinds of a card event.
EVENT_KINDS: tuple[str, ...] = (
    "created",
    "moved",
    "assigned",
    "due",
    "linked",
    "unlinked",
    "checklist",
    "renamed",
    "archived",
    "restored",
)
#: The target kinds of a link, in the order of the link picker.
LINK_KINDS: tuple[str, ...] = (
    "application",
    "meeting",
    "agenda_item",
    "vote",
    "appointment",
    "gremium",
    "invoice",
    "expense",
    "order",
    "event",
    "budget",
    "ticket",
    "todo",
    "paperless",
)
#: The table of each link kind; a trigger on it deletes the links of a deleted row.
LINK_TABLES: dict[str, str] = {
    "application": "application",
    "meeting": "meeting",
    "agenda_item": "meeting_agenda_item",
    "vote": "vote",
    "appointment": "calendar_appointment",
    "gremium": "gremium",
    "invoice": "invoice",
    "expense": "budget_expense",
    "order": "purchase_order",
    "event": "event",
    "budget": "budget",
    "ticket": "ticket",
    "todo": "todo_card",
    "paperless": "paperless_document",
}
#: The columns of a new board, by position; the last one is the done column.
DEFAULT_COLUMNS: tuple[str, ...] = ("Offen", "In Arbeit", "Wartet", "Erledigt")
#: The name of a new personal board.
PERSONAL_BOARD_NAME = "Meine To-Dos"
#: The permission board that the migration creates for the ticket team.
PERMISSION_BOARD_NAME = "Plattform"
PERMISSION_BOARD_PERMISSION = "ticket.manage"


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class TodoBoard(UUIDPkMixin, TimestampMixin, Base):
    """A board of a team, of one account, of a permission or a free board."""

    __tablename__ = "todo_board"

    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("team.id", ondelete="CASCADE"), nullable=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principal.id"), nullable=True)
    permission: Mapped[str | None] = mapped_column(Text, nullable=True)
    archive_after_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True, server_default="30"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"kind IN ({_in(BOARD_KINDS)})", name="kind"),
        CheckConstraint(
            "(kind = 'team' AND team_id IS NOT NULL AND owner_id IS NULL "
            "AND permission IS NULL) OR "
            "(kind = 'personal' AND owner_id IS NOT NULL AND team_id IS NULL "
            "AND permission IS NULL) OR "
            "(kind = 'permission' AND permission IS NOT NULL AND team_id IS NULL "
            "AND owner_id IS NULL) OR "
            "(kind = 'free' AND team_id IS NULL AND owner_id IS NULL "
            "AND permission IS NULL)",
            name="owner",
        ),
        CheckConstraint(
            "archive_after_days IS NULL OR archive_after_days BETWEEN 1 AND 365",
            name="archive_after_days",
        ),
        Index(
            "uq_todo_board_team",
            "team_id",
            unique=True,
            postgresql_where=text("team_id IS NOT NULL"),
        ),
        Index(
            "uq_todo_board_owner",
            "owner_id",
            unique=True,
            postgresql_where=text("owner_id IS NOT NULL"),
        ),
    )


class TodoBoardEntry(UUIDPkMixin, Base):
    """A member entry of a board: one team or one person, with a role.

    A team entry stands for the members of the team at the time of the read (spec
    003068), so the row names the team and never its members.
    """

    __tablename__ = "todo_board_entry"

    board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_board.id", ondelete="CASCADE"))
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("team.id", ondelete="CASCADE"), nullable=True
    )
    principal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), nullable=True
    )
    role: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"role IN ({_in(ENTRY_ROLES)})", name="role"),
        CheckConstraint("(team_id IS NULL) <> (principal_id IS NULL)", name="target"),
        Index(
            "uq_todo_board_entry_team",
            "board_id",
            "team_id",
            unique=True,
            postgresql_where=text("team_id IS NOT NULL"),
        ),
        Index(
            "uq_todo_board_entry_principal",
            "board_id",
            "principal_id",
            unique=True,
            postgresql_where=text("principal_id IS NOT NULL"),
        ),
        Index("ix_todo_board_entry_team_id", "team_id"),
        Index("ix_todo_board_entry_principal_id", "principal_id"),
    )


class TodoColumn(UUIDPkMixin, Base):
    """A column of a board. Exactly one column of a board is the done column."""

    __tablename__ = "todo_column"

    board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_board.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    is_done: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        Index(
            "uq_todo_column_done",
            "board_id",
            unique=True,
            postgresql_where=text("is_done"),
        ),
        Index("ix_todo_column_board_id", "board_id"),
    )


class TodoCard(UUIDPkMixin, TimestampMixin, Base):
    """A card. ``rank`` orders it in its column; ``version`` guards content edits.

    The column has no cascade, so a column with cards cannot be deleted (409
    ``column_not_empty``).
    """

    __tablename__ = "todo_card"

    board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_board.id", ondelete="CASCADE"))
    column_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_column.id"))
    rank: Mapped[str] = mapped_column(Text(collation="C"))
    title: Mapped[str] = mapped_column(Text)
    description_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_reminded_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principal.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, server_default="1")

    __table_args__ = (
        Index("ix_todo_card_board_column_rank", "board_id", "column_id", "rank"),
        Index(
            "ix_todo_card_due_date",
            "due_date",
            postgresql_where=text("archived_at IS NULL"),
        ),
    )


class TodoEventSeries(UUIDPkMixin, TimestampMixin, Base):
    """A series of Events (``Reihe``); the name is unique in the platform."""

    __tablename__ = "todo_event_series"

    name: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("uq_todo_event_series_name", text("lower(name)"), unique=True),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="name"),
    )


class TodoAssignee(Base):
    """A person responsible for a card."""

    __tablename__ = "todo_assignee"

    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_card.id", ondelete="CASCADE"))
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principal.id"))

    __table_args__ = (
        PrimaryKeyConstraint("card_id", "principal_id"),
        Index("ix_todo_assignee_principal_id", "principal_id"),
    )


class TodoLabel(UUIDPkMixin, Base):
    """A label of a board. The name is unique per board, case-insensitive."""

    __tablename__ = "todo_label"

    board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_board.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(f"color IN ({_in(LABEL_COLORS)})", name="color"),
        Index("uq_todo_label_board_name", "board_id", func.lower(text("name")), unique=True),
    )


class TodoCardLabel(Base):
    """A label on a card."""

    __tablename__ = "todo_card_label"

    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_card.id", ondelete="CASCADE"))
    label_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_label.id", ondelete="CASCADE"))

    __table_args__ = (PrimaryKeyConstraint("card_id", "label_id"),)


class TodoCheckItem(UUIDPkMixin, Base):
    """One item of the checklist of a card."""

    __tablename__ = "todo_check_item"

    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_card.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    done: Mapped[bool] = mapped_column(Boolean, server_default="false")
    position: Mapped[int] = mapped_column(Integer, server_default="0")

    __table_args__ = (Index("ix_todo_check_item_card_id", "card_id"),)


class TodoComment(UUIDPkMixin, Base):
    """A comment on a card (Markdown). ``mentions`` holds principal ids."""

    __tablename__ = "todo_comment"

    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_card.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principal.id"))
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_todo_comment_card_id", "card_id"),)


class TodoEvent(UUIDPkMixin, Base):
    """One timeline event of a card. ``actor_id`` NULL means the system."""

    __tablename__ = "todo_event"

    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_card.id", ondelete="CASCADE"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principal.id"), nullable=True)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"kind IN ({_in(EVENT_KINDS)})", name="kind"),
        Index("ix_todo_event_card_id", "card_id"),
    )


LinkEnd = tuple[str, uuid.UUID]


def _order_key(end: LinkEnd) -> tuple[bytes, bytes]:
    return (end[0].encode(), end[1].bytes)


def ordered_ends(one: LinkEnd, other: LinkEnd) -> tuple[LinkEnd, LinkEnd]:
    """The two ends in the stored order: by kind (byte order), then by id.

    The byte order is the order of Postgres with ``COLLATE "C"`` and of ``uuid``, so the
    migration orders the rows of ``todo_link`` the same way.
    """
    return (one, other) if _order_key(one) <= _order_key(other) else (other, one)


class Link(UUIDPkMixin, Base):
    """A link between two elements, without direction (spec 001401)."""

    __tablename__ = "link"

    a_kind: Mapped[str] = mapped_column(Text)
    a_id: Mapped[uuid.UUID] = mapped_column()
    b_kind: Mapped[str] = mapped_column(Text)
    b_id: Mapped[uuid.UUID] = mapped_column()
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principal.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"a_kind IN ({_in(LINK_KINDS)})", name="a_kind"),
        CheckConstraint(f"b_kind IN ({_in(LINK_KINDS)})", name="b_kind"),
        CheckConstraint("NOT (a_kind = b_kind AND a_id = b_id)", name="not_self"),
        CheckConstraint(
            "NOT (a_kind = 'paperless' AND b_kind = 'paperless')", name="one_paperless"
        ),
        Index("uq_link_ends", "a_kind", "a_id", "b_kind", "b_id", unique=True),
        Index("ix_link_b", "b_kind", "b_id"),
    )

    @classmethod
    def between(
        cls, one: LinkEnd, other: LinkEnd, actor: uuid.UUID, at: datetime | None = None
    ) -> Link:
        """A new link between two ends, in the stored order."""
        (a_kind, a_id), (b_kind, b_id) = ordered_ends(one, other)
        return cls(
            id=uuid.uuid4(),
            a_kind=a_kind,
            a_id=a_id,
            b_kind=b_kind,
            b_id=b_id,
            created_by=actor,
            **({"created_at": at} if at is not None else {}),
        )

    def other(self, end: LinkEnd) -> LinkEnd:
        """The end that is not ``end``."""
        if (self.a_kind, self.a_id) == end:
            return (self.b_kind, self.b_id)
        return (self.a_kind, self.a_id)

    def has_end(self, end: LinkEnd) -> bool:
        """Tell if ``end`` is one of the two ends."""
        return end in ((self.a_kind, self.a_id), (self.b_kind, self.b_id))
