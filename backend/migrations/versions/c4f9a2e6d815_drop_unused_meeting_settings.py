"""Meeting settings: drop the two values that the platform no longer has.

The upgrade drops from `meeting_settings`:

- `protocol_draft_days`: the value was stored and drove nothing
  (§F/administration/admin/000917).
- `confirm_lead_minutes` and its check `ck_meeting_settings_confirm_lead`: a meeting
  opens from `open_lead_minutes` before its start without an extra confirmation
  (§F/meetings/meetings/000092).

Idempotent. The downgrade adds the columns with their start values (14 and 10) again
and sets `confirm_lead_minutes` to at most `open_lead_minutes`, so the check holds.

Revision ID: c4f9a2e6d815
Revises: b3e8d1f47a52
Create Date: 2026-11-15 22:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c4f9a2e6d815"
down_revision: str | None = "b3e8d1f47a52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the two columns and the check."""
    op.execute(
        "ALTER TABLE meeting_settings DROP CONSTRAINT IF EXISTS ck_meeting_settings_confirm_lead"
    )
    op.execute("ALTER TABLE meeting_settings DROP COLUMN IF EXISTS confirm_lead_minutes")
    op.execute("ALTER TABLE meeting_settings DROP COLUMN IF EXISTS protocol_draft_days")


def downgrade() -> None:
    """Add the two columns and the check again."""
    op.execute(
        "ALTER TABLE meeting_settings ADD COLUMN IF NOT EXISTS protocol_draft_days "
        "integer NOT NULL DEFAULT 14"
    )
    op.execute(
        "ALTER TABLE meeting_settings ADD COLUMN IF NOT EXISTS confirm_lead_minutes "
        "integer NOT NULL DEFAULT 10"
    )
    op.execute(
        "UPDATE meeting_settings SET confirm_lead_minutes = "
        "LEAST(confirm_lead_minutes, open_lead_minutes)"
    )
    op.execute(
        "ALTER TABLE meeting_settings DROP CONSTRAINT IF EXISTS ck_meeting_settings_confirm_lead"
    )
    op.execute(
        "ALTER TABLE meeting_settings ADD CONSTRAINT ck_meeting_settings_confirm_lead "
        "CHECK (confirm_lead_minutes BETWEEN 0 AND open_lead_minutes)"
    )
