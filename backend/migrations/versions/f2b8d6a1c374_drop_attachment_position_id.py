"""Attachment: drop the link to a position (spec 001730 removed).

A position of a ``positions`` field no longer takes its own files, so
``attachment.position_id`` goes. The files stay attachments of their Antrag.

Idempotent. A fresh database never has the column, because the ``create_all`` baseline
(0001) reads the current model.

Revision ID: f2b8d6a1c374
Revises: e7a4c2d9f150
Create Date: 2026-11-24 23:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f2b8d6a1c374"
down_revision: str | None = "e7a4c2d9f150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the link."""
    op.execute("ALTER TABLE attachment DROP COLUMN IF EXISTS position_id")


def downgrade() -> None:
    """Add the column back, empty."""
    op.execute("ALTER TABLE attachment ADD COLUMN IF NOT EXISTS position_id text")
