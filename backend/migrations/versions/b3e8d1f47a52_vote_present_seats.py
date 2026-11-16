"""Vote: the pool substitutes on a seat when the vote closed.

The upgrade adds to `vote` the column `present_seats` (integer, NULL). The close of a
meeting vote sets it, next to `present_members`. Without it a closed vote counted the
seats of the meeting of today, so a later change of the delegations changed the quorum
that the closed vote shows. A vote that closed before the column exists keeps NULL and
counts the seats of the meeting, as before.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001).

Revision ID: b3e8d1f47a52
Revises: a7d3e9b15c64
Create Date: 2026-11-15 19:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b3e8d1f47a52"
down_revision: str | None = "a7d3e9b15c64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the seat count of a closed vote."""
    op.execute("ALTER TABLE vote ADD COLUMN IF NOT EXISTS present_seats integer")


def downgrade() -> None:
    """Drop the seat count of a closed vote."""
    op.execute("ALTER TABLE vote DROP COLUMN IF EXISTS present_seats")
