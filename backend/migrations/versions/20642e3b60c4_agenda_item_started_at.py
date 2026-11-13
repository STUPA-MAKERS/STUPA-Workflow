"""agenda_item_started_at: the time at which a live meeting moved to an agenda item.

The upgrade adds the nullable column ``started_at`` to ``meeting_agenda_item``. The
first move of a live meeting to the item sets it, and a later move back keeps it.
NULL means that the meeting never reached the item. There is no backfill, because
the old moves are no stored fact. The protocol PDF shows the time above the TOP.

Idempotent. A fresh database already gets the column from the ``create_all``
baseline (0001), and a migrated database gets it through ``ADD COLUMN IF NOT
EXISTS``.

The downgrade drops the column. The times are lost.

Revision ID: 20642e3b60c4
Revises: fea8282a392b
Create Date: 2026-11-13 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20642e3b60c4"
down_revision: str | None = "fea8282a392b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the start time of an agenda item."""
    op.execute("ALTER TABLE meeting_agenda_item ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ")


def downgrade() -> None:
    """Drop the start time of an agenda item."""
    op.execute("ALTER TABLE meeting_agenda_item DROP COLUMN IF EXISTS started_at")
