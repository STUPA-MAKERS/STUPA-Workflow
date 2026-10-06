"""Add `status_event.vote_id`, the vote whose close fired the event.

A meeting delete now deletes all votes of the meeting (it replaces F21). An
application that such a vote decided keeps its status. Its timeline must then show
"vote deleted (with its meeting)" instead of a link to the vote. The timeline can do
that only when the status event names its vote.

The upgrade:

1. adds the nullable column `status_event.vote_id` with a foreign key to `vote`
   (`ON DELETE SET NULL`) and the index `ix_status_event_vote_id`. Each step is
   idempotent, because a fresh database already gets them from the `create_all`
   baseline (0001).
2. fills the column for the older branch events (note `vote:<result>`). It takes the
   closed vote of the same application whose `result_branch_transition_id` is the
   transition of the event. When more than one vote fits, it takes the vote whose
   `closed_at` is nearest to the event. An event without such a vote keeps NULL: the
   meeting delete before F21 deleted its vote.

The downgrade drops the column, with its index and its foreign key.

Revision ID: ed7ea60b3551
Revises: e12bd65b2a79
Create Date: 2026-10-06 17:33:23.530492
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "ed7ea60b3551"
down_revision: str | None = "e12bd65b2a79"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_status_event_vote_id_vote"


def upgrade() -> None:
    op.execute("ALTER TABLE status_event ADD COLUMN IF NOT EXISTS vote_id uuid")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'status_event'::regclass AND conname = '{_FK}'
            ) THEN
                ALTER TABLE status_event ADD CONSTRAINT {_FK}
                    FOREIGN KEY (vote_id) REFERENCES vote (id) ON DELETE SET NULL;
            END IF;
        END $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_status_event_vote_id ON status_event (vote_id)"
    )
    op.execute(
        """
        UPDATE status_event AS se
           SET vote_id = m.vote_id
          FROM (
                SELECT DISTINCT ON (e.id) e.id AS event_id, v.id AS vote_id
                  FROM status_event AS e
                  JOIN vote AS v
                    ON v.application_id = e.application_id
                   AND v.result_branch_transition_id = e.transition_id
                   AND v.status = 'closed'
                 WHERE e.note LIKE 'vote:%'
                   AND e.vote_id IS NULL
                 ORDER BY e.id,
                          abs(extract(epoch FROM (coalesce(v.closed_at, e.at) - e.at)))
               ) AS m
         WHERE se.id = m.event_id
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_status_event_vote_id")
    op.execute(f"ALTER TABLE status_event DROP CONSTRAINT IF EXISTS {_FK}")
    op.execute("ALTER TABLE status_event DROP COLUMN IF EXISTS vote_id")
