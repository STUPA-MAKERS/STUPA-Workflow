"""Application type: drop the switch "Unterschriften im PDF" (spec 003009).

The Antrag PDF ends with the signature rows of its Antragsart whenever the list has a row,
so ``application_type.pdf_signatures`` goes. The rows stay as they are.

Idempotent. A fresh database never has the column, because the ``create_all`` baseline
(0001) reads the current model.

Revision ID: e7a4c2d9f150
Revises: 9d3a6c0e7b52
Create Date: 2026-11-24 23:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e7a4c2d9f150"
down_revision: str | None = "9d3a6c0e7b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the switch."""
    op.execute("ALTER TABLE application_type DROP COLUMN IF EXISTS pdf_signatures")


def downgrade() -> None:
    """Add the switch back, off for every Antragsart."""
    op.execute(
        "ALTER TABLE application_type "
        "ADD COLUMN IF NOT EXISTS pdf_signatures boolean NOT NULL DEFAULT false"
    )
