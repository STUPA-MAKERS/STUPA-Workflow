"""drop_webhook_events: remove the event list of a webhook.

A webhook sends only when a flow transition runs its ``webhook`` action. No code reads
``webhook.events``, so the upgrade drops the column.

Migration 0001 builds a fresh schema from the current models, so both statements are
idempotent.

**The data change is one-way.** The downgrade adds the column again with an empty list
for every webhook. It does not restore the dropped values.

Revision ID: 08dfb2c28b9a
Revises: 84414cd99f16
Create Date: 2026-11-06 15:20:51.705534
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "08dfb2c28b9a"
down_revision: str | None = "84414cd99f16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop ``webhook.events``."""
    op.execute("ALTER TABLE webhook DROP COLUMN IF EXISTS events")


def downgrade() -> None:
    """Add ``webhook.events`` again, empty for every webhook."""
    op.execute("ALTER TABLE webhook ADD COLUMN IF NOT EXISTS events text[] NOT NULL DEFAULT '{}'")
