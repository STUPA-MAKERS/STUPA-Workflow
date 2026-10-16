"""Reporter chat on tickets: ``ticket_note.visibility``, nullable ``ticket_note.author_id``.

The upgrade:

1. adds ``ticket_note.visibility`` (``internal`` or ``public``, default ``internal``).
   Every existing note was written as an internal note, so it stays ``internal`` and
   the reporter never reads it.
2. drops ``NOT NULL`` from ``ticket_note.author_id``. The anonymization of a ticket
   clears the author of the notes that the reporter wrote, because the author is the
   reporter.

Every key is named like the baseline names it, so both paths match. All steps are
idempotent. A fresh database already gets the column from the ``create_all`` baseline
(0001), because the models sit in ``app.models``.

The downgrade deletes the notes without an author (the old column takes no NULL),
restores ``NOT NULL`` and drops the column with its check.

Revision ID: 071d20ab0e10
Revises: 269d13cd80a8
Create Date: 2026-10-16 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "071d20ab0e10"
down_revision: str | None = "269d13cd80a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_ticket_note_visibility"

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE ticket_note ADD COLUMN IF NOT EXISTS visibility text NOT NULL DEFAULT 'internal'",
    f"ALTER TABLE ticket_note DROP CONSTRAINT IF EXISTS {_CHECK}",
    (
        f"ALTER TABLE ticket_note ADD CONSTRAINT {_CHECK} "
        "CHECK (visibility IN ('internal', 'public'))"
    ),
    "ALTER TABLE ticket_note ALTER COLUMN author_id DROP NOT NULL",
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM ticket_note WHERE author_id IS NULL",
    "ALTER TABLE ticket_note ALTER COLUMN author_id SET NOT NULL",
    f"ALTER TABLE ticket_note DROP CONSTRAINT IF EXISTS {_CHECK}",
    "ALTER TABLE ticket_note DROP COLUMN IF EXISTS visibility",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
