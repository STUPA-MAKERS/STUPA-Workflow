"""Allow only `present` and `excused` for a self-reported attendance (Z2).

The upgrade adds the check `ck_meeting_attendance_self_status`:
`source <> 'self' OR status IN ('present', 'excused')`. A member reports the own
attendance as present or excused. Only the meeting lead records `absent`.

The check is `NOT VALID`. Postgres checks each new and each changed row, but it
does not check the rows that exist. An older `(self, absent)` row therefore
stays as it is, and the attendance of a closed meeting keeps matching the
protocol PDF that went out. A change to such a row must set an allowed status.
The migration logs the number of these rows.

The step is idempotent: a fresh database already gets the check from the
`create_all` baseline (0001), so the upgrade drops it first and adds it again as
`NOT VALID`.

The downgrade drops the check.

Revision ID: 96421ecdbc54
Revises: d5569d5542c6
Create Date: 2026-10-01 21:37:24.045305
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "96421ecdbc54"
down_revision: str | None = "d5569d5542c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_CK = "ck_meeting_attendance_self_status"


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(f"ALTER TABLE meeting_attendance DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(
        f"ALTER TABLE meeting_attendance ADD CONSTRAINT {_CK} "
        "CHECK (source <> 'self' OR status IN ('present', 'excused')) NOT VALID"
    )
    legacy = bind.execute(
        sa.text(
            "SELECT count(*) FROM meeting_attendance "
            "WHERE source = 'self' AND status NOT IN ('present', 'excused')"
        )
    ).scalar_one()
    logger.info(
        "meeting_attendance: %d older self-reported row(s) with status 'absent' "
        "stay as they are (check is NOT VALID)",
        legacy,
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE meeting_attendance DROP CONSTRAINT IF EXISTS {_CK}")
