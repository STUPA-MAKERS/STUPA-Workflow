"""Gremium: its own start month of the term.

The upgrade adds to `gremium` the column `term_start_month` (integer, NOT NULL, default
10). Each Gremium that exists gets `term_start_month` of `meeting_settings`, because
this one value was the term of every Gremium before (spec 000948). From now on the value
of the settings is only the start value of a new Gremium.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001) and no Gremium, so the copy changes nothing there.

Revision ID: a7d3e9b15c64
Revises: f2c5a7d94e31
Create Date: 2026-11-15 18:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a7d3e9b15c64"
down_revision: str | None = "f2c5a7d94e31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the start month and copy the value of the settings to each Gremium."""
    op.execute(
        "ALTER TABLE gremium ADD COLUMN IF NOT EXISTS term_start_month integer NOT NULL DEFAULT 10"
    )
    op.execute(
        "UPDATE gremium SET term_start_month = s.term_start_month "
        "FROM meeting_settings s WHERE s.id = 1"
    )


def downgrade() -> None:
    """Drop the start month of the Gremium."""
    op.execute("ALTER TABLE gremium DROP COLUMN IF EXISTS term_start_month")
