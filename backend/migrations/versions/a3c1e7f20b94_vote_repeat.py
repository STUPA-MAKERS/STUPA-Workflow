"""vote_repeat: a meeting vote can repeat a closed vote of the same agenda item.

``repeat_of_id`` points from the repeat to the closed vote that it repeats, and
``attempt`` counts the votes of that chain (1 for a first vote, 2 for the first repeat).
The repeated vote stays with its result, because the protocol records that the room
voted again. The foreign key is ``SET NULL``, so a delete of the old vote keeps the
repeat. Both columns are new and empty, so the downgrade drops them without data loss
in other tables.

Revision ID: a3c1e7f20b94
Revises: 334e15ec6ff5
Create Date: 2026-11-05 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a3c1e7f20b94"
down_revision: str | None = "334e15ec6ff5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Migration 0001 builds a fresh schema from the current models, so every statement is
#: idempotent: a fresh install already has the columns, the key and the index.
_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS repeat_of_id uuid",
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS attempt integer NOT NULL DEFAULT 1",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid = 'vote'::regclass AND conname = 'fk_vote_repeat_of_id_vote'
        ) THEN
            ALTER TABLE vote ADD CONSTRAINT fk_vote_repeat_of_id_vote
                FOREIGN KEY (repeat_of_id) REFERENCES vote (id) ON DELETE SET NULL;
        END IF;
    END $$
    """,
    "CREATE INDEX IF NOT EXISTS ix_vote_repeat_of_id ON vote (repeat_of_id)",
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_vote_repeat_of_id",
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS fk_vote_repeat_of_id_vote",
    "ALTER TABLE vote DROP COLUMN IF EXISTS attempt",
    "ALTER TABLE vote DROP COLUMN IF EXISTS repeat_of_id",
)


def upgrade() -> None:
    """Add ``vote.repeat_of_id`` (FK SET NULL, indexed) and ``vote.attempt``."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the two columns of the repeat."""
    for statement in _DOWNGRADE:
        op.execute(statement)
