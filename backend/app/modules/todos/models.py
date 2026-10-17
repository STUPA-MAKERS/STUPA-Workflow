"""To-do tables: boards, columns, cards and everything that hangs on a card.

A board has one of three kinds, and the kind decides its owner column:

* ``gremium`` — ``gremium_id``; one board per gremium (``uq_todo_board_gremium``).
* ``personal`` — ``owner_id``; one board per account (``uq_todo_board_owner``).
* ``team`` — ``permission``; the holders of that global permission.

``ck_todo_board_owner`` keeps exactly the owner column of the kind set.

A board has exactly one done column (partial unique index ``uq_todo_column_done``).
A card in the done column carries ``completed_at``; a move out clears it. A card
sorts inside its column by ``rank``, a lexorank string with the collation ``C``, so
a move writes one row only (``lexorank.py``). ``version`` guards the content edits
(title, description, due date) against a lost update.

``todo_link`` points a card at exactly one target: an application, a meeting, an
agenda item, a ticket or another card. ``todo_event`` is the timeline of a card;
there is no audit entry for to-dos.

``due_reminded_on`` is the due date that the ``todo_due`` reminder went out for. A
changed due date gets a new reminder.
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
BOARD_KINDS: tuple[str, ...] = ("gremium", "personal", "team")
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
LINK_KINDS: tuple[str, ...] = ("application", "meeting", "agenda_item", "ticket", "todo")
#: The target column of each link kind.
LINK_COLUMNS: dict[str, str] = {
    "application": "application_id",
    "meeting": "meeting_id",
    "agenda_item": "agenda_item_id",
    "ticket": "ticket_id",
    "todo": "todo_id",
}
#: The columns of a new board, by position; the last one is the done column.
DEFAULT_COLUMNS: tuple[str, ...] = ("Offen", "In Arbeit", "Wartet", "Erledigt")
#: The name of a new personal board.
PERSONAL_BOARD_NAME = "Meine To-Dos"
#: The team board that the migration creates for the ticket team.
TEAM_BOARD_NAME = "Plattform"
TEAM_BOARD_PERMISSION = "ticket.manage"


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class TodoBoard(UUIDPkMixin, TimestampMixin, Base):
    """A board of a gremium, of one account or of a permission (team)."""

    __tablename__ = "todo_board"

    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True
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
            "(kind = 'gremium' AND gremium_id IS NOT NULL AND owner_id IS NULL "
            "AND permission IS NULL) OR "
            "(kind = 'personal' AND owner_id IS NOT NULL AND gremium_id IS NULL "
            "AND permission IS NULL) OR "
            "(kind = 'team' AND permission IS NOT NULL AND gremium_id IS NULL "
            "AND owner_id IS NULL)",
            name="owner",
        ),
        CheckConstraint(
            "archive_after_days IS NULL OR archive_after_days BETWEEN 1 AND 365",
            name="archive_after_days",
        ),
        Index(
            "uq_todo_board_gremium",
            "gremium_id",
            unique=True,
            postgresql_where=text("gremium_id IS NOT NULL"),
        ),
        Index(
            "uq_todo_board_owner",
            "owner_id",
            unique=True,
            postgresql_where=text("owner_id IS NOT NULL"),
        ),
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
    """A card. ``rank`` orders it in its column; ``version`` guards content edits."""

    __tablename__ = "todo_card"

    board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_board.id", ondelete="CASCADE"))
    # No cascade: a column with cards cannot be deleted (409 column_not_empty).
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


class TodoLink(UUIDPkMixin, Base):
    """A link from a card to exactly one target."""

    __tablename__ = "todo_link"

    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo_card.id", ondelete="CASCADE"))
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True
    )
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meeting.id", ondelete="CASCADE"), nullable=True
    )
    agenda_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meeting_agenda_item.id", ondelete="CASCADE"), nullable=True
    )
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ticket.id", ondelete="CASCADE"), nullable=True
    )
    todo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("todo_card.id", ondelete="CASCADE"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("principal.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(application_id, meeting_id, agenda_item_id, ticket_id, todo_id) = 1",
            name="one_target",
        ),
        Index("ix_todo_link_card_id", "card_id"),
        *(
            Index(
                f"uq_todo_link_{column}",
                "card_id",
                column,
                unique=True,
                postgresql_where=text(f"{column} IS NOT NULL"),
            )
            for column in LINK_COLUMNS.values()
        ),
        *(
            Index(f"ix_todo_link_{column}", column, postgresql_where=text(f"{column} IS NOT NULL"))
            for column in LINK_COLUMNS.values()
        ),
    )

    @property
    def kind(self) -> str:
        """The kind of the target (the one set target column)."""
        for kind, column in LINK_COLUMNS.items():
            if getattr(self, column) is not None:
                return kind
        raise ValueError("todo_link without a target")  # pragma: no cover - check constraint

    @property
    def target_id(self) -> uuid.UUID:
        """The id of the target."""
        value: uuid.UUID = getattr(self, LINK_COLUMNS[self.kind])
        return value
