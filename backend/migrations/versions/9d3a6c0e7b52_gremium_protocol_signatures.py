"""Gremium: the signature lines of the protocol PDF (spec 003007).

``gremium`` gets ``protocol_signatures``. Every existing Gremium gets the two lines that
the protocol PDF showed before the lines became a setting, so an existing protocol does
not change. A new Gremium starts with an empty list.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001); the update then fills only the lists that are still empty.

Revision ID: 9d3a6c0e7b52
Revises: 5b8e2f71c9a4
Create Date: 2026-11-24 22:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d3a6c0e7b52"
down_revision: str | None = "5b8e2f71c9a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the lines and give every existing Gremium the two former lines."""
    op.execute(
        "ALTER TABLE gremium "
        "ADD COLUMN IF NOT EXISTS protocol_signatures text[] NOT NULL DEFAULT '{}'"
    )
    op.execute(
        sa.text(
            "UPDATE gremium SET protocol_signatures = ARRAY[:first, :second]::text[] "
            "WHERE cardinality(protocol_signatures) = 0"
        ).bindparams(first="Schriftführung", second="Vorstand")
    )


def downgrade() -> None:
    """Drop the lines."""
    op.execute("ALTER TABLE gremium DROP COLUMN IF EXISTS protocol_signatures")
