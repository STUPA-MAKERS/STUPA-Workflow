"""Form fields: the display format of a computed field.

The upgrade adds the nullable column ``form_field.display_format`` (§F/applications/forms/
002962). ``NULL`` is the format ``number``, so every existing field keeps its display.

Revision ID: 1cab2fdfd7ea
Revises: b7e3d1a9c460
Create Date: 2026-11-24 19:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1cab2fdfd7ea"
down_revision: str | None = "b7e3d1a9c460"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the display format of a form field."""
    op.add_column("form_field", sa.Column("display_format", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the display format. A computed field then shows as a number."""
    op.drop_column("form_field", "display_format")
