"""Drafts and new versions of an Antrag (specs 001711, 001720-001722).

The upgrade adds three columns, each idempotent:

- ``application.replaces_id``: the Antrag that this one is a new version of, with an
  index and a foreign key that sets NULL on a delete.
- ``application.draft_reminder_at``: when the reminder mail of a draft went out.
- ``state.is_replaced_target``: the state that takes an Antrag when its new version is
  submitted.

A fresh database already gets them from the ``create_all`` baseline (0001), because the
models sit in ``app.models``. The downgrade drops the three columns.

Revision ID: d7e2a9c41b38
Revises: c5e19a7d3b42
Create Date: 2026-11-19 23:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d7e2a9c41b38"
down_revision: str | None = "c5e19a7d3b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``replaces_id``, ``draft_reminder_at`` and ``is_replaced_target``."""
    op.execute(
        """
        ALTER TABLE application
            ADD COLUMN IF NOT EXISTS replaces_id uuid
                CONSTRAINT fk_application_replaces_id_application
                REFERENCES application (id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS draft_reminder_at timestamp with time zone
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_application_replaces_id ON application (replaces_id)")
    op.execute(
        "ALTER TABLE state ADD COLUMN IF NOT EXISTS is_replaced_target boolean "
        "NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    """Drop the three columns."""
    op.execute("ALTER TABLE state DROP COLUMN IF EXISTS is_replaced_target")
    op.execute("DROP INDEX IF EXISTS ix_application_replaces_id")
    op.execute(
        "ALTER TABLE application DROP COLUMN IF EXISTS draft_reminder_at, "
        "DROP COLUMN IF EXISTS replaces_id"
    )
