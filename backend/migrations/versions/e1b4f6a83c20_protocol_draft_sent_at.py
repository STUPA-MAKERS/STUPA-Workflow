"""Protocol: the time of the last draft mail.

The upgrade adds to `protocol` the column `draft_sent_at` (timestamptz, NULL). The send
of a draft to the members stores its time there, and a second send asks first (spec
000937). A draft that went out before the column keeps NULL.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001).

Revision ID: e1b4f6a83c20
Revises: d5a2c7e41b90
Create Date: 2026-11-15 16:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e1b4f6a83c20"
down_revision: str | None = "d5a2c7e41b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the time of the last draft mail."""
    op.execute("ALTER TABLE protocol ADD COLUMN IF NOT EXISTS draft_sent_at timestamptz")


def downgrade() -> None:
    """Drop the time of the last draft mail."""
    op.execute("ALTER TABLE protocol DROP COLUMN IF EXISTS draft_sent_at")
