"""Meeting: the late-excuse period of the time the meeting was made.

The upgrade adds to `meeting` the column `late_excuse_days` (integer, NULL). A new
meeting stores there `lateExcuseDays` of the settings, so a later change of the setting
does not move its window (spec 000942). A meeting from before the column keeps NULL and
takes the setting.

The upgrade also raises the two invitation periods, `late_excuse_days` and
`circular_min_days` of `meeting_settings` from 0 to 1, because the API accepts only 1
day or more from now on and a stored 0 would fail the read of the settings.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001).

Revision ID: f2c5a7d94e31
Revises: e1b4f6a83c20
Create Date: 2026-11-15 17:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f2c5a7d94e31"
down_revision: str | None = "e1b4f6a83c20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AT_LEAST_ONE = (
    "invite_days_ordinary",
    "invite_days_extraordinary",
    "late_excuse_days",
    "circular_min_days",
)


def upgrade() -> None:
    """Add the kept period and raise a stored period of 0 days to 1."""
    op.execute("ALTER TABLE meeting ADD COLUMN IF NOT EXISTS late_excuse_days integer")
    for column in _AT_LEAST_ONE:
        op.execute(f"UPDATE meeting_settings SET {column} = 1 WHERE {column} < 1")


def downgrade() -> None:
    """Drop the kept period. A raised period stays, because its old value is not stored."""
    op.execute("ALTER TABLE meeting DROP COLUMN IF EXISTS late_excuse_days")
