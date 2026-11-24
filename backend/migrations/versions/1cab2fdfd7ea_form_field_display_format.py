"""Form fields: the display format of a computed field.

The upgrade adds the nullable column ``form_field.display_format`` (§F/applications/forms/
002962). ``NULL`` is the format ``number``, so every existing field keeps its display.

Revision ID: 1cab2fdfd7ea
Revises: b7e3d1a9c460
Create Date: 2026-11-24 19:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "1cab2fdfd7ea"
down_revision: str | None = "b7e3d1a9c460"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the display format of a form field.

    ``IF NOT EXISTS``, because the baseline builds a fresh database from the models, which
    already have the column.
    """
    op.execute("ALTER TABLE form_field ADD COLUMN IF NOT EXISTS display_format text")


def downgrade() -> None:
    """Drop the display format. A computed field then shows as a number."""
    op.execute("ALTER TABLE form_field DROP COLUMN IF EXISTS display_format")
