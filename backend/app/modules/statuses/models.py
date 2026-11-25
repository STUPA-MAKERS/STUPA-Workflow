"""The table ``status_def``: one row per status of a status list.

A list is named by its element kind (``order``, ``event``). A row holds the key, which
never changes after the create, the name per UI language, the tone of the display, the
position in the list, the phase and the flag of the start status (003035). ``sets_date``
names the date of a Bestellung that a change to the status fills (003037).

The stored elements hold the key of their status, not the id of the row, because a save
of a list replaces its rows and the key stays the same (003040).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin

#: The element kinds that have a status list.
STATUS_LISTS: tuple[str, ...] = ("order", "event")
#: The phases of a status (F/administration/admin/003036).
STATUS_PHASES: tuple[str, ...] = ("open", "done", "void")
#: The tones of the display of a status: the kinds of the kit status text.
STATUS_TONES: tuple[str, ...] = ("neutral", "accent", "warn", "error", "muted")
#: The dates of a Bestellung that a status can fill (003037).
STATUS_DATES: tuple[str, ...] = ("orderedOn", "deliveredOn")


def _in(values: tuple[str, ...]) -> str:
    """Render the values as the list of an SQL ``IN``."""
    return ", ".join(f"'{value}'" for value in values)


class StatusDef(UUIDPkMixin, CreatedAtMixin, Base):
    """One status of the status list of an element kind."""

    __tablename__ = "status_def"

    list_kind: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    tone: Mapped[str] = mapped_column(Text, server_default="neutral")
    phase: Mapped[str] = mapped_column(Text)
    is_start: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    sets_date: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("list_kind", "key", name="uq_status_def_list_key"),
        UniqueConstraint("list_kind", "position", name="uq_status_def_list_position"),
        CheckConstraint(f"list_kind IN ({_in(STATUS_LISTS)})", name="list_kind"),
        CheckConstraint(f"phase IN ({_in(STATUS_PHASES)})", name="phase"),
        CheckConstraint(f"tone IN ({_in(STATUS_TONES)})", name="tone"),
        CheckConstraint(
            f"sets_date IS NULL OR (list_kind = 'order' AND sets_date IN ({_in(STATUS_DATES)}))",
            name="sets_date",
        ),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint("NOT is_start OR phase = 'open'", name="start_open"),
        Index(
            "uq_status_def_start",
            "list_kind",
            unique=True,
            postgresql_where=text("is_start"),
        ),
    )
