"""Approval with deviations (F1): `application_decision`, two new columns.

The upgrade:

1. creates the table `application_decision`: one row per decision on an application
   (approved amount, conditions, the vote or the status event that carried it). The
   valid decision is the row with `superseded_at IS NULL`; a partial unique index
   allows at most one such row per application.
2. adds `application.approved_amount`, the denormalized amount of the valid decision
   (NULL = as requested).
3. adds `vote.proposal`, the decision proposal of an application vote.

Every step is idempotent. A fresh database already gets the table and the columns from
the `create_all` baseline (0001), because the models sit in `app.models`.

The downgrade drops the table and the two columns.

Revision ID: 5a67ac7644ed
Revises: bf0309071fb4
Create Date: 2026-10-09 12:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5a67ac7644ed"
down_revision: str | None = "bf0309071fb4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS application_decision (
        id uuid DEFAULT gen_random_uuid(),
        application_id uuid NOT NULL,
        approved_amount numeric(12, 2),
        conditions jsonb NOT NULL DEFAULT '[]'::jsonb,
        vote_id uuid,
        status_event_id uuid,
        decided_at timestamptz NOT NULL DEFAULT now(),
        decided_by text,
        superseded_at timestamptz,
        -- Named like the metadata naming convention, so a fresh install (create_all)
        -- and an upgraded install carry the same constraint names.
        CONSTRAINT pk_application_decision PRIMARY KEY (id),
        CONSTRAINT fk_application_decision_application_id_application
            FOREIGN KEY (application_id) REFERENCES application (id) ON DELETE CASCADE,
        CONSTRAINT fk_application_decision_vote_id_vote
            FOREIGN KEY (vote_id) REFERENCES vote (id) ON DELETE SET NULL,
        CONSTRAINT fk_application_decision_status_event_id_status_event
            FOREIGN KEY (status_event_id) REFERENCES status_event (id) ON DELETE SET NULL
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_application_decision_application_id "
        "ON application_decision (application_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_application_decision_status_event_id "
        "ON application_decision (status_event_id)"
    ),
    # At most one valid decision per application.
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_application_decision_one_valid "
        "ON application_decision (application_id) WHERE superseded_at IS NULL"
    ),
    "ALTER TABLE application ADD COLUMN IF NOT EXISTS approved_amount numeric(12, 2)",
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS proposal jsonb",
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE vote DROP COLUMN IF EXISTS proposal",
    "ALTER TABLE application DROP COLUMN IF EXISTS approved_amount",
    "DROP TABLE IF EXISTS application_decision",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
