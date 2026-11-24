"""Ticket mail: a mail tells whether its sender is checked.

The upgrade adds ``ticket_mail.sender_checked`` (§F/integrations/ticket-mail/002816). An
imported mail counts as checked only when it answers a mail that the Postfach sent to
its ``From`` address. Each mail that is already stored stays unchecked, because the
check was not made at its import. The step is idempotent.

Revision ID: e0dd72d776c9
Revises: b9e2c47f1a36
Create Date: 2026-11-24 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e0dd72d776c9"
down_revision: str | None = "b9e2c47f1a36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the column ``sender_checked``."""
    op.execute(
        "ALTER TABLE ticket_mail "
        "ADD COLUMN IF NOT EXISTS sender_checked BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    """Drop the column ``sender_checked``."""
    op.execute("ALTER TABLE ticket_mail DROP COLUMN IF EXISTS sender_checked")
