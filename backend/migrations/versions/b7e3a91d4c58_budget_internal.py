"""Budget tree: the switch "Intern" of a cost center (003011).

``budget`` gets ``internal`` (false). A node is Intern when its own switch or the
switch of a node above it is on. The form field ``budget_select`` offers no Intern node
(003012).

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001), because the model sits in ``app.models``.

Revision ID: b7e3a91d4c58
Revises: f2b8d6a1c374
Create Date: 2026-11-25 09:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b7e3a91d4c58"
down_revision: str | None = "f2b8d6a1c374"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the switch, off for every cost center."""
    op.execute(
        "ALTER TABLE budget ADD COLUMN IF NOT EXISTS internal boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    """Drop the switch."""
    op.execute("ALTER TABLE budget DROP COLUMN IF EXISTS internal")
