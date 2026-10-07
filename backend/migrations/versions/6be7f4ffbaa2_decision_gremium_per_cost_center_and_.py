"""Add `budget.decision_gremium_id` and the snapshot `application.vote_gremium_id`.

Flow variant B: a vote state can take its deciding Gremium from the cost center of the
application (`config.gremiumSource: "budget"`). The upgrade:

1. adds the nullable column `budget.decision_gremium_id` (foreign key to `gremium`,
   `ON DELETE SET NULL`) with the index `ix_budget_decision_gremium_id`. A node without
   an own value inherits the value of the nearest ancestor.
2. adds the nullable column `application.vote_gremium_id` (foreign key to `gremium`,
   `ON DELETE SET NULL`) with the index `ix_application_vote_gremium_id`. The flow
   engine sets it when an application enters a vote state and clears it when the
   application leaves the vote state.
3. fills `application.vote_gremium_id` for every application that is now in a vote
   state, from the `config.gremiumId` of that state. A value that names no existing
   Gremium stays NULL.

Each schema step is idempotent, because a fresh database already gets the columns from
the `create_all` baseline (0001).

The downgrade drops both columns with their indexes and foreign keys.

Revision ID: 6be7f4ffbaa2
Revises: ed7ea60b3551
Create Date: 2026-10-07 10:29:18.174229
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "6be7f4ffbaa2"
down_revision: str | None = "ed7ea60b3551"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, foreign-key name, index name)
_COLUMNS: tuple[tuple[str, str, str, str], ...] = (
    (
        "budget",
        "decision_gremium_id",
        "fk_budget_decision_gremium_id_gremium",
        "ix_budget_decision_gremium_id",
    ),
    (
        "application",
        "vote_gremium_id",
        "fk_application_vote_gremium_id_gremium",
        "ix_application_vote_gremium_id",
    ),
)


def upgrade() -> None:
    for table, column, fk, ix in _COLUMNS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} uuid")
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                     WHERE conrelid = '{table}'::regclass AND conname = '{fk}'
                ) THEN
                    ALTER TABLE {table} ADD CONSTRAINT {fk}
                        FOREIGN KEY ({column}) REFERENCES gremium (id) ON DELETE SET NULL;
                END IF;
            END $$
            """
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS {ix} ON {table} ({column})")
    # Backfill: an application in a vote state gets the fixed Gremium of that state.
    # Only an existing Gremium qualifies, so the foreign key holds. The compare ignores
    # the case, because a config can hold the UUID in upper case.
    op.execute(
        """
        UPDATE application AS a
           SET vote_gremium_id = g.id
          FROM state AS s
          JOIN gremium AS g ON lower(g.id::text) = lower(s.config ->> 'gremiumId')
         WHERE a.current_state_id = s.id
           AND s.kind = 'vote'
           AND a.vote_gremium_id IS NULL
        """
    )


def downgrade() -> None:
    for table, column, fk, ix in reversed(_COLUMNS):
        op.execute(f"DROP INDEX IF EXISTS {ix}")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {fk}")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
