"""meeting: end_time (#ics).

The optional end time of a meeting, next to `start_time`. The iCal subscription
uses it as `DTEND`. If the value is NULL, the feed assumes a default duration of
one hour. The column is nullable and the statement is idempotent
(`IF NOT EXISTS`). A fresh schema already has the column from `create_all`
(0001).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029_meeting_end_time"
down_revision: str | None = "0028_principal_calendar_token"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE meeting ADD COLUMN IF NOT EXISTS end_time time")


def downgrade() -> None:
    op.execute("ALTER TABLE meeting DROP COLUMN IF EXISTS end_time")
