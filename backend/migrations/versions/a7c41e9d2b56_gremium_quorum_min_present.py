"""Gremium: the least number of present roster persons for the quorum.

``gremium`` gets ``quorum_min_present`` (nullable). NULL means that only the percent
quorum counts. A meeting vote copies the value to its config when it is created.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001).

Revision ID: a7c41e9d2b56
Revises: 6d89f29dead1
Create Date: 2026-11-14 11:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a7c41e9d2b56"
down_revision: str | None = "6d89f29dead1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the column, empty for every Gremium."""
    op.execute("ALTER TABLE gremium ADD COLUMN IF NOT EXISTS quorum_min_present INTEGER")


def downgrade() -> None:
    """Drop the column."""
    op.execute("ALTER TABLE gremium DROP COLUMN IF EXISTS quorum_min_present")
