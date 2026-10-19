"""drop_attachment_comparison_offer: an attachment no longer carries a comparison-offer mark.

The mark ``attachment.is_comparison_offer`` controlled nothing: no validation, no
flow guard and no budget rule read it. The comparison offers that count are the offers
of the cost positions in the form answers. The upgrade drops the column.

Idempotent. A fresh database never gets the column from the ``create_all`` baseline
(0001), because ``Attachment`` no longer declares it. A migrated database loses it
through ``DROP COLUMN IF EXISTS``.

The downgrade adds the column again with ``false`` for every row. The old marks are
lost.

Revision ID: 43dd9c193645
Revises: 527854b79d68
Create Date: 2026-10-19 13:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "43dd9c193645"
down_revision: str | None = "527854b79d68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the comparison-offer mark of the attachments."""
    op.execute("ALTER TABLE attachment DROP COLUMN IF EXISTS is_comparison_offer")


def downgrade() -> None:
    """Add the mark again, false for every row."""
    op.execute(
        "ALTER TABLE attachment ADD COLUMN IF NOT EXISTS is_comparison_offer "
        "BOOLEAN NOT NULL DEFAULT false"
    )
