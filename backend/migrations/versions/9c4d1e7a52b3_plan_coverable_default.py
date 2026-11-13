"""Haushaltsplan: a budget says if its plan lines start deckungsfähig.

``budget`` gets ``plan_coverable_default`` (false). The upgrade changes no plan line.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001), because the model sits in ``app.models``.

Revision ID: 9c4d1e7a52b3
Revises: 31e525795fd9
Create Date: 2026-11-13 21:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "9c4d1e7a52b3"
down_revision: str | None = "31e525795fd9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the setting, off for every budget."""
    op.execute(
        "ALTER TABLE budget ADD COLUMN IF NOT EXISTS plan_coverable_default boolean "
        "NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    """Drop the setting."""
    op.execute("ALTER TABLE budget DROP COLUMN IF EXISTS plan_coverable_default")
