"""Haushaltsplan: the vote of a plan step runs in a meeting.

1. ``meeting_agenda_item`` gets ``plan_version_id``: the plan version that an agenda
   item decides. One meeting has a version once.
2. A vote on a plan version without a meeting ends, because the vote of a step now
   belongs to an agenda item: a draft is deleted, and an open vote is cancelled.

The upgrade writes no audit entry: it changes the form of the data and decides nothing.

Idempotent. A fresh database already has the column and the index from the
``create_all`` baseline (0001), because the model sits in ``app.models``.

One-way: the downgrade drops the column. The votes that ended stay ended.

Revision ID: 31e525795fd9
Revises: fea8282a392b
Create Date: 2026-11-13 19:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "31e525795fd9"
down_revision: str | None = "fea8282a392b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_meeting_agenda_item_plan_version_id_budget_plan_version"

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE meeting_agenda_item ADD COLUMN IF NOT EXISTS plan_version_id uuid",
    f"""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{_FK}') THEN
            ALTER TABLE meeting_agenda_item ADD CONSTRAINT {_FK}
                FOREIGN KEY (plan_version_id) REFERENCES budget_plan_version (id)
                ON DELETE SET NULL;
        END IF;
    END
    $$
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_agenda_meeting_plan_version
        ON meeting_agenda_item (meeting_id, plan_version_id)
        WHERE plan_version_id IS NOT NULL
    """,
    """
    DELETE FROM vote
     WHERE plan_version_id IS NOT NULL AND meeting_id IS NULL AND status = 'draft'
    """,
    """
    UPDATE vote
       SET status = 'cancelled', closed_at = now()
     WHERE plan_version_id IS NOT NULL AND meeting_id IS NULL AND status = 'open'
    """,
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP INDEX IF EXISTS uq_agenda_meeting_plan_version",
    "ALTER TABLE meeting_agenda_item DROP COLUMN IF EXISTS plan_version_id",
)


def upgrade() -> None:
    """Add the plan version of an agenda item and end the plan votes without a meeting."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the plan version of an agenda item."""
    for statement in _DOWNGRADE:
        op.execute(statement)
