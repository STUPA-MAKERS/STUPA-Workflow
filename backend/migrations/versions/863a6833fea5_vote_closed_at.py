"""Add `vote.closed_at`, remove `allowChange` from the vote configs, report meeting ties.

`vote.closed_at` is the real moment when a vote ended (close or cancel, Z9 and O10).
It is not `closes_at`, which is the planned end of the cast window.

The upgrade:

1. adds the column. This is idempotent: a fresh database already gets the column from
   the `create_all` baseline (0001), and a migrated database gets it through
   `ADD COLUMN IF NOT EXISTS`.
2. backfills it from the audit log where possible. A closed application vote that
   fired its result branch has a `status_change` audit entry for that transition:
   `target_id` is the application and `data.transitionId` is
   `vote.result_branch_transition_id`. The earliest such entry at or after the open
   time is the close time. All other votes keep NULL: the audit log holds no close
   time for them. The migration logs both counts.
3. removes the key `allowChange` from `vote.config`. A ballot never changes after the
   cast (O11), so `VoteConfig` has no such field. `VoteConfig` refuses unknown keys
   (`extra=forbid`), so the old rows must lose the key to stay valid.
4. reports the closed meeting votes with the result `tie` (O18). From now on a meeting
   vote stores `tieBreak=rejected`, so a tie is `rejected`. The migration does not
   change a recorded result.

The downgrade drops the column. It does not restore `allowChange`: the old default
was `true`, and the old code reads a missing key as that default.

Revision ID: 863a6833fea5
Revises: 1a9feecb23a5
Create Date: 2026-10-01 08:56:09.231555
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "863a6833fea5"
down_revision: str | None = "1a9feecb23a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_BACKFILL = """
UPDATE vote AS v
   SET closed_at = src.at
  FROM (
        SELECT v2.id AS vote_id, min(a.at) AS at
          FROM vote AS v2
          JOIN audit_entry AS a
            ON a.action = 'status_change'
           AND a.target_type = 'application'
           AND a.target_id = v2.application_id::text
           AND a.data->>'transitionId' = v2.result_branch_transition_id::text
           AND a.at >= COALESCE(v2.opens_at, v2.created_at)
         WHERE v2.status = 'closed'
           AND v2.closed_at IS NULL
           AND v2.application_id IS NOT NULL
           AND v2.result_branch_transition_id IS NOT NULL
         GROUP BY v2.id
       ) AS src
 WHERE v.id = src.vote_id
RETURNING v.id
"""


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TABLE vote ADD COLUMN IF NOT EXISTS closed_at timestamptz")

    filled = len(bind.execute(sa.text(_BACKFILL)).all())
    left = bind.execute(
        sa.text(
            "SELECT count(*) FROM vote "
            "WHERE status IN ('closed', 'cancelled') AND closed_at IS NULL"
        )
    ).scalar_one()
    logger.info(
        "vote.closed_at: %d vote(s) backfilled from the audit log, "
        "%d ended vote(s) without a known close time stay NULL",
        filled,
        left,
    )

    stripped = bind.execute(
        sa.text(
            "UPDATE vote SET config = config - 'allowChange' "
            "WHERE config ? 'allowChange' RETURNING id"
        )
    ).all()
    if stripped:
        logger.info("removed allowChange from the config of %d vote(s)", len(stripped))

    ties = bind.execute(
        sa.text(
            "SELECT id, meeting_id FROM vote "
            "WHERE meeting_id IS NOT NULL AND result = 'tie' ORDER BY created_at"
        )
    ).all()
    for vote_id, meeting_id in ties:
        logger.warning(
            "meeting vote %s (meeting %s) has the result 'tie'; new meeting votes "
            "count a tie as 'rejected' (O18). The recorded result stays.",
            vote_id,
            meeting_id,
        )


def downgrade() -> None:
    # `allowChange` is not restored: see the module docstring.
    op.execute("ALTER TABLE vote DROP COLUMN IF EXISTS closed_at")
