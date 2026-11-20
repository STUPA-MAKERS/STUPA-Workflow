"""Form rules, the switch "Anhang Pflicht" and the files of a position.

``form_version`` gets ``rules`` (spec 001670), an empty list for every existing version.
``application_type`` gets ``attachment_required`` (spec 001732), off for every existing
type. ``attachment`` gets ``position_id`` (spec 001730), NULL for every existing file.

Idempotent. A fresh database already has the columns from the ``create_all`` baseline
(0001).

Revision ID: b7d3e1f0a9c4
Revises: c4e8a1f07b52
Create Date: 2026-11-19 23:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b7d3e1f0a9c4"
down_revision: str | None = "c4e8a1f07b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the three columns."""
    op.execute(
        "ALTER TABLE form_version ADD COLUMN IF NOT EXISTS rules jsonb NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE application_type "
        "ADD COLUMN IF NOT EXISTS attachment_required boolean NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE attachment ADD COLUMN IF NOT EXISTS position_id text")


def downgrade() -> None:
    """Drop the three columns."""
    op.execute("ALTER TABLE attachment DROP COLUMN IF EXISTS position_id")
    op.execute("ALTER TABLE application_type DROP COLUMN IF EXISTS attachment_required")
    op.execute("ALTER TABLE form_version DROP COLUMN IF EXISTS rules")
