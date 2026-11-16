"""Haushaltsplan: a draft line holds the new name and the new key of its cost center.

``budget_plan_line`` gets ``draft_name`` and ``draft_key``. A draft sets them, and they
apply to the cost center when the version comes into force.

Idempotent. A fresh database already has both from the ``create_all`` baseline
(0001), because the model sits in ``app.models``.

Revision ID: 4b8e2f6c1a93
Revises: c41d7e9a2b63
Create Date: 2026-11-13 23:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "4b8e2f6c1a93"
down_revision: str | None = "c41d7e9a2b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the new name and the new key of a draft line."""
    op.execute("ALTER TABLE budget_plan_line ADD COLUMN IF NOT EXISTS draft_name text")
    op.execute("ALTER TABLE budget_plan_line ADD COLUMN IF NOT EXISTS draft_key text")


def downgrade() -> None:
    """Drop the new name and the new key of a draft line."""
    op.execute("ALTER TABLE budget_plan_line DROP COLUMN IF EXISTS draft_key")
    op.execute("ALTER TABLE budget_plan_line DROP COLUMN IF EXISTS draft_name")
