"""Meeting: the first meeting of a Wiederholungssitzung.

The upgrade adds to `meeting` the column `repeat_of_id` (uuid, NULL, FK `meeting`,
SET NULL). A meeting of the kind `repeat` names there the earlier meeting that had no
quorum (spec 000940). A repeat meeting from before the column keeps NULL.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001).

Revision ID: d5a2c7e41b90
Revises: c3f8a1d92e57
Create Date: 2026-11-15 15:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d5a2c7e41b90"
down_revision: str | None = "c3f8a1d92e57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the reference to the first meeting."""
    op.execute(
        "ALTER TABLE meeting ADD COLUMN IF NOT EXISTS repeat_of_id uuid "
        "REFERENCES meeting(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    """Drop the reference to the first meeting."""
    op.execute("ALTER TABLE meeting DROP COLUMN IF EXISTS repeat_of_id")
