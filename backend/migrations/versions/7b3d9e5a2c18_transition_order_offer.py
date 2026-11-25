"""Flow: a transition can be offered at a status change of a Bestellung.

The upgrade adds ``transition.offer_on_order_status`` (F/finance/orders/002931): NULL,
``ordered`` or ``delivered``. The step is idempotent, because a fresh database already
gets the column from the ``create_all`` baseline (0001).

Revision ID: 7b3d9e5a2c18
Revises: 5e8a1c7d3f42
Create Date: 2026-11-24 21:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "7b3d9e5a2c18"
down_revision: str | None = "5e8a1c7d3f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.execute("ALTER TABLE transition ADD COLUMN IF NOT EXISTS offer_on_order_status TEXT")


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    op.execute("ALTER TABLE transition DROP COLUMN IF EXISTS offer_on_order_status")
