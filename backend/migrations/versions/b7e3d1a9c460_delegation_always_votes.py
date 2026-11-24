"""Delegations: every delegation carries the vote.

The upgrade sets ``meeting_delegation.delegate_voting`` to true on every delegation of a
planned meeting (§F/meetings/delegations/002901) and makes true the server default
(§F/meetings/delegations/002900). A delegation of a live or closed meeting keeps its value,
because its counts are history.

Revision ID: b7e3d1a9c460
Revises: f4a9c2d7e815
Create Date: 2026-11-24 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b7e3d1a9c460"
down_revision: str | None = "f4a9c2d7e815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Give the vote to the delegations of planned meetings and default to true."""
    op.execute("ALTER TABLE meeting_delegation ALTER COLUMN delegate_voting SET DEFAULT true")
    op.execute(
        "UPDATE meeting_delegation SET delegate_voting = true "
        "WHERE delegate_voting IS NOT true "
        "AND meeting_id IN (SELECT id FROM meeting WHERE status = 'planned')"
    )


def downgrade() -> None:
    """Restore the old server default. The changed rows keep the vote."""
    op.execute("ALTER TABLE meeting_delegation ALTER COLUMN delegate_voting SET DEFAULT false")
