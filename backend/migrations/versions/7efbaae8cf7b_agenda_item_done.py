"""agenda_item_done: a person ticks an agenda item as done.

The upgrade adds two nullable columns to ``meeting_agenda_item``: ``done_at`` (the
time of the tick) and ``done_by`` (the ``sub`` of the person who ticked it). NULL
means "not done". There is no backfill. The old display marked every item before the
current item as done by its position, and that is no stored fact.

Idempotent. A fresh database already gets both columns from the ``create_all``
baseline (0001), and a migrated database gets them through ``ADD COLUMN IF NOT
EXISTS``.

The downgrade drops both columns. The ticks are lost.

Revision ID: 7efbaae8cf7b
Revises: 43dd9c193645
Create Date: 2026-10-22 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "7efbaae8cf7b"
down_revision: str | None = "43dd9c193645"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the done mark of an agenda item."""
    op.execute("ALTER TABLE meeting_agenda_item ADD COLUMN IF NOT EXISTS done_at TIMESTAMPTZ")
    op.execute("ALTER TABLE meeting_agenda_item ADD COLUMN IF NOT EXISTS done_by TEXT")


def downgrade() -> None:
    """Drop the done mark of an agenda item."""
    op.execute("ALTER TABLE meeting_agenda_item DROP COLUMN IF EXISTS done_by")
    op.execute("ALTER TABLE meeting_agenda_item DROP COLUMN IF EXISTS done_at")
