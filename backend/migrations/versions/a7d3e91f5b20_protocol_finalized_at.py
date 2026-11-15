"""protocol_finalized_at: the finalization and the mail of a protocol have two moments.

The upgrade adds ``protocol.finalized_at`` and fills it from ``sent_at`` for every final
protocol, because ``sent_at`` held the moment of the finalization until now. ``sent_at``
keeps its values: an old protocol counts as sent, as the page said before.

Idempotent. A fresh database already gets the column from the ``create_all`` baseline
(0001), so the step uses ``IF NOT EXISTS``, and the data step fills only empty values.

The downgrade drops the column.

Revision ID: a7d3e91f5b20
Revises: c4f9a2e6d815
Create Date: 2026-11-15 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a7d3e91f5b20"
down_revision: str | None = "c4f9a2e6d815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.execute("ALTER TABLE protocol ADD COLUMN IF NOT EXISTS finalized_at timestamptz")
    op.execute(
        "UPDATE protocol SET finalized_at = sent_at "
        "WHERE finalized_at IS NULL AND sent_at IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    op.execute("ALTER TABLE protocol DROP COLUMN IF EXISTS finalized_at")
