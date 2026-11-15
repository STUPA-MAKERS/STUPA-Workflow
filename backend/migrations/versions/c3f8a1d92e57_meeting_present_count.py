"""Meeting: the present count and the member count fixed at the close.

The upgrade adds to `meeting` the columns `present_count` and `eligible_count`
(integer, NULL). The close of a meeting sets them (spec 000946). A meeting that
closed before keeps NULL, and a reader then counts from the rows of today.

Idempotent. A fresh database already has the columns from the ``create_all`` baseline
(0001).

Revision ID: c3f8a1d92e57
Revises: b6e21d07c9a4
Create Date: 2026-11-15 14:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c3f8a1d92e57"
down_revision: str | None = "b6e21d07c9a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: tuple[str, ...] = ("present_count", "eligible_count")


def upgrade() -> None:
    """Add the two count columns."""
    for column in _COLUMNS:
        op.execute(f"ALTER TABLE meeting ADD COLUMN IF NOT EXISTS {column} integer")


def downgrade() -> None:
    """Drop the two count columns."""
    for column in _COLUMNS:
        op.execute(f"ALTER TABLE meeting DROP COLUMN IF EXISTS {column}")
