"""fiscal_year_closed: a fiscal year can be closed ("abgeschlossen").

The upgrade adds two nullable columns to the table `fiscal_year`:

1. `closed_at` (timestamptz): the moment of the close. NULL means open.
2. `closed_by` (text): the subject of the principal who closed the year.

A closed year is frozen. The service refuses every money mutation on it with
409 `fiscal_year_closed`. Every existing year stays open.

All statements are idempotent (`IF NOT EXISTS` / `IF EXISTS`). A fresh database
already gets the columns from the `create_all` baseline (0001).

The downgrade drops both columns, so every year is open again.

Revision ID: b7c41e9a2f53
Revises: e029878bed05
Create Date: 2026-10-25 13:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b7c41e9a2f53"
down_revision: str | None = "e029878bed05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE fiscal_year ADD COLUMN IF NOT EXISTS closed_at timestamptz",
    "ALTER TABLE fiscal_year ADD COLUMN IF NOT EXISTS closed_by text",
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE fiscal_year DROP COLUMN IF EXISTS closed_by",
    "ALTER TABLE fiscal_year DROP COLUMN IF EXISTS closed_at",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
