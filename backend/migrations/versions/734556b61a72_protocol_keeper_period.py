"""Add the periods of the protocol keeper (Z3).

The upgrade creates the table `protocol_keeper_period`. A row is one period in
which one principal keeps the minutes of a meeting. A period is planned
(`from_at` is NULL), running (`to_at` is NULL) or ended. The check
`ck_protocol_keeper_period_period_range` makes sure that an ended period has a
start and does not end before it. Two partial unique indexes allow at most one
running and at most one planned period per meeting.

The step is idempotent: a fresh database already gets the table from the
`create_all` baseline (0001), so the statements use `IF NOT EXISTS`.

Backfill: each `live` or `closed` meeting with a protokollant gets one period for
that protokollant, when it has no period yet.

* `from_at` is the real start (`started_at`). Without it, the planned date and
  start time in Europe/Berlin. Without a date, the creation time of the meeting.
* `to_at` of a closed meeting is `closed_at`, or `from_at` without it. The value
  never goes below `from_at`: a meeting can close before its planned start, and
  the check refuses an end before the start.
* A live meeting keeps a running period (`to_at` is NULL).
* `handed_over_by` is `system:migration`. The agenda items stay NULL, because no
  record tells which item was current.

The migration logs the number of backfilled periods.

The downgrade drops the table.

Revision ID: 734556b61a72
Revises: 1ee8a0d3928c
Create Date: 2026-10-02 00:37:11.685034
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "734556b61a72"
down_revision: str | None = "1ee8a0d3928c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_CREATE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS protocol_keeper_period (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        meeting_id uuid NOT NULL
            CONSTRAINT fk_protocol_keeper_period_meeting_id_meeting
            REFERENCES meeting (id) ON DELETE CASCADE,
        principal_id uuid NOT NULL
            CONSTRAINT fk_protocol_keeper_period_principal_id_principal
            REFERENCES principal (id),
        from_at timestamptz,
        to_at timestamptz,
        from_agenda_item_id uuid
            CONSTRAINT fk_protocol_keeper_period_from_item
            REFERENCES meeting_agenda_item (id) ON DELETE SET NULL,
        to_agenda_item_id uuid
            CONSTRAINT fk_protocol_keeper_period_to_item
            REFERENCES meeting_agenda_item (id) ON DELETE SET NULL,
        handed_over_by text NOT NULL,
        CONSTRAINT ck_protocol_keeper_period_period_range
            CHECK (to_at IS NULL OR (from_at IS NOT NULL AND to_at >= from_at))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_protocol_keeper_period_meeting "
    "ON protocol_keeper_period (meeting_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_protocol_keeper_period_running "
    "ON protocol_keeper_period (meeting_id) WHERE from_at IS NOT NULL AND to_at IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_protocol_keeper_period_planned "
    "ON protocol_keeper_period (meeting_id) WHERE from_at IS NULL",
)

# One period per live or closed meeting with a protokollant and without a period.
_BACKFILL = """
    INSERT INTO protocol_keeper_period (meeting_id, principal_id, from_at, to_at, handed_over_by)
    SELECT m.id, m.protokollant_id, s.from_at,
           CASE WHEN m.status = 'closed'
                THEN GREATEST(COALESCE(m.closed_at, s.from_at), s.from_at)
           END,
           'system:migration'
    FROM meeting m
    CROSS JOIN LATERAL (
        SELECT COALESCE(
            m.started_at,
            CASE WHEN m.date IS NOT NULL
                 THEN (m.date + COALESCE(m.start_time, TIME '00:00'))
                      AT TIME ZONE 'Europe/Berlin'
            END,
            m.created_at
        ) AS from_at
    ) s
    WHERE m.status IN ('live', 'closed')
      AND m.protokollant_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM protocol_keeper_period p WHERE p.meeting_id = m.id
      )
"""


def upgrade() -> None:
    for stmt in _CREATE:
        op.execute(stmt)
    added = op.get_bind().execute(sa.text(_BACKFILL)).rowcount
    logger.info("protocol_keeper_period: %d period(s) backfilled from meeting", added)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS protocol_keeper_period")
