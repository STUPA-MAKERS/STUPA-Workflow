"""Personnel elections (F2): vote kind, runoff link, election result.

The upgrade adds to the table `vote`:

1. `kind` (text, NOT NULL, default `motion`, CHECK `ck_vote_vote_kind` in
   `motion`/`election`). Every existing row is a motion.
2. `parent_vote_id` (FK `vote.id`, ON DELETE SET NULL): the election that a runoff
   continues.
3. `round` (integer, NOT NULL, default 1): the round of the election.
4. `election_result` (JSONB, nullable): the result of a closed election.
5. The result CHECK also allows `elected` and `runoff`. A motion keeps `passed`,
   `rejected` and `tie`.

All statements are idempotent (`IF NOT EXISTS` / `IF EXISTS`). A fresh database
already gets the columns and the constraints from the `create_all` baseline (0001).
The baseline names the result CHECK `ck_vote_vote_result`; a very old database can
still hold it as `vote_result`, so the upgrade drops both names.

The downgrade deletes the election rows (their ballots cascade), restores the old
result CHECK and drops the columns.

Revision ID: d9de5b02cbb8
Revises: 5a67ac7644ed
Create Date: 2026-10-09 12:06:57.659032
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d9de5b02cbb8"
down_revision: str | None = "5a67ac7644ed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'motion'",
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS parent_vote_id uuid",
    # Named like the metadata naming convention (a fresh install gets the same name).
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid = 'vote'::regclass AND conname = 'fk_vote_parent_vote_id_vote'
        ) THEN
            ALTER TABLE vote ADD CONSTRAINT fk_vote_parent_vote_id_vote
                FOREIGN KEY (parent_vote_id) REFERENCES vote (id) ON DELETE SET NULL;
        END IF;
    END $$
    """,
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS round integer NOT NULL DEFAULT 1",
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS election_result jsonb",
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS ck_vote_vote_kind",
    "ALTER TABLE vote ADD CONSTRAINT ck_vote_vote_kind CHECK (kind IN ('motion','election'))",
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS vote_result",
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS ck_vote_vote_result",
    (
        "ALTER TABLE vote ADD CONSTRAINT ck_vote_vote_result CHECK "
        "(result IS NULL OR result IN ('passed','rejected','tie','elected','runoff'))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    # The narrower CHECK and the dropped columns cannot hold an election.
    "DELETE FROM protocol_vote_ref WHERE vote_id IN (SELECT id FROM vote WHERE kind = 'election')",
    "UPDATE status_event SET vote_id = NULL "
    "WHERE vote_id IN (SELECT id FROM vote WHERE kind = 'election')",
    "DELETE FROM vote WHERE kind = 'election'",
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS ck_vote_vote_result",
    (
        "ALTER TABLE vote ADD CONSTRAINT ck_vote_vote_result CHECK "
        "(result IS NULL OR result IN ('passed','rejected','tie'))"
    ),
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS ck_vote_vote_kind",
    "ALTER TABLE vote DROP COLUMN IF EXISTS election_result",
    "ALTER TABLE vote DROP COLUMN IF EXISTS round",
    "ALTER TABLE vote DROP COLUMN IF EXISTS parent_vote_id",
    "ALTER TABLE vote DROP COLUMN IF EXISTS kind",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
