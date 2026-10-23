"""vote_poll: polls with free options ("Umfrage").

The upgrade changes the table `vote`:

1. The kind CHECK `ck_vote_vote_kind` also allows `poll`.
2. `poll_result` (JSONB, nullable): the counts of a closed poll. A poll keeps
   `result` NULL.
3. `reminded_at` (timestamptz, nullable): the moment of the one reminder mail of a
   poll without a meeting, 24 h before its end.

All statements are idempotent (`IF NOT EXISTS` / `IF EXISTS`). A fresh database
already gets the columns and the constraint from the `create_all` baseline (0001).

The downgrade deletes the poll rows (their ballots cascade), restores the old kind
CHECK and drops the columns.

Revision ID: e029878bed05
Revises: 7efbaae8cf7b
Create Date: 2026-10-22 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e029878bed05"
down_revision: str | None = "7efbaae8cf7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS poll_result jsonb",
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS reminded_at timestamptz",
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS ck_vote_vote_kind",
    (
        "ALTER TABLE vote ADD CONSTRAINT ck_vote_vote_kind "
        "CHECK (kind IN ('motion','election','poll'))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    # The narrower CHECK cannot hold a poll.
    "DELETE FROM protocol_vote_ref WHERE vote_id IN (SELECT id FROM vote WHERE kind = 'poll')",
    "DELETE FROM vote WHERE kind = 'poll'",
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS ck_vote_vote_kind",
    "ALTER TABLE vote ADD CONSTRAINT ck_vote_vote_kind CHECK (kind IN ('motion','election'))",
    "ALTER TABLE vote DROP COLUMN IF EXISTS reminded_at",
    "ALTER TABLE vote DROP COLUMN IF EXISTS poll_result",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
