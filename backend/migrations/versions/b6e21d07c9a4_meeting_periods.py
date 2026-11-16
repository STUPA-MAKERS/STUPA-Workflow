"""Meeting settings: the periods of the Geschäftsordnung; protocol: the approval.

The upgrade adds to `meeting_settings`:

- `invite_days_ordinary` (7) and `invite_days_extraordinary` (3): the invitation
  periods of a meeting, in days.
- `protocol_draft_days` (14): the days until the draft of a protocol is due.
- `late_excuse_days` (7): the days after the close in which a member can still give
  an excuse.
- `absence_limit` (3): the number of unexcused absences in one term.
- `term_start_month` (10): the month on whose first day a term starts.

It adds to `protocol` the approval of a final protocol: `approved_at`,
`approved_meeting_id` (FK `meeting`, SET NULL) and `approved_by`.

Idempotent. A fresh database already has all of this from the ``create_all`` baseline
(0001).

Revision ID: b6e21d07c9a4
Revises: a47c0e93b1d6
Create Date: 2026-11-14 23:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b6e21d07c9a4"
down_revision: str | None = "a47c0e93b1d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERIODS: tuple[tuple[str, int], ...] = (
    ("invite_days_ordinary", 7),
    ("invite_days_extraordinary", 3),
    ("protocol_draft_days", 14),
    ("late_excuse_days", 7),
    ("absence_limit", 3),
    ("term_start_month", 10),
)
_APPROVAL: tuple[str, ...] = ("approved_at", "approved_meeting_id", "approved_by")


def upgrade() -> None:
    """Add the period columns and the approval columns."""
    for column, start in _PERIODS:
        op.execute(
            f"ALTER TABLE meeting_settings ADD COLUMN IF NOT EXISTS {column} "
            f"integer NOT NULL DEFAULT {start}"
        )
    op.execute("ALTER TABLE protocol ADD COLUMN IF NOT EXISTS approved_at timestamptz")
    op.execute(
        "ALTER TABLE protocol ADD COLUMN IF NOT EXISTS approved_meeting_id uuid "
        "REFERENCES meeting(id) ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE protocol ADD COLUMN IF NOT EXISTS approved_by text")


def downgrade() -> None:
    """Drop the approval columns and the period columns."""
    for column in _APPROVAL:
        op.execute(f"ALTER TABLE protocol DROP COLUMN IF EXISTS {column}")
    for column, _start in _PERIODS:
        op.execute(f"ALTER TABLE meeting_settings DROP COLUMN IF EXISTS {column}")
