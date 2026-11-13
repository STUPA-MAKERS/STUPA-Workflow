"""Antragsart: the switch for the signature section of the Antrag PDF (spec 000888).

``application_type`` gets ``pdf_signatures``, off for every existing type.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001).

Revision ID: c41d7e9a2b63
Revises: 9c4d1e7a52b3
Create Date: 2026-11-13 22:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c41d7e9a2b63"
down_revision: str | None = "9c4d1e7a52b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the switch, off."""
    op.execute(
        "ALTER TABLE application_type "
        "ADD COLUMN IF NOT EXISTS pdf_signatures boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    """Drop the switch."""
    op.execute("ALTER TABLE application_type DROP COLUMN IF EXISTS pdf_signatures")
