"""Meetings: an agenda item carries an estimated duration in minutes (spec 001140).

``meeting_agenda_item`` gets ``estimated_minutes``, a whole number from 1 to 480.
NULL means no estimate: the time plan of the agenda counts the item as 0 minutes
(spec 001141).

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001), because the model sits in ``app.models``.

Revision ID: 9f610130db84
Revises: a3f1c7e2d905
Create Date: 2026-11-16 15:20:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "9f610130db84"
down_revision: str | None = "a3f1c7e2d905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_meeting_agenda_item_estimated_minutes"

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE meeting_agenda_item ADD COLUMN IF NOT EXISTS estimated_minutes integer",
    f"""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid = 'meeting_agenda_item'::regclass
               AND conname = '{_CHECK}'
        ) THEN
            ALTER TABLE meeting_agenda_item ADD CONSTRAINT {_CHECK}
                CHECK (estimated_minutes BETWEEN 1 AND 480);
        END IF;
    END $$
    """,
)


def upgrade() -> None:
    """Add the estimated duration of an agenda item."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the estimated duration of an agenda item."""
    op.execute(f"ALTER TABLE meeting_agenda_item DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.execute("ALTER TABLE meeting_agenda_item DROP COLUMN IF EXISTS estimated_minutes")
