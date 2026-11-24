"""Paperless: an embedded PDF keeps the number of its Paperless document.

``markdown_document.paperless_document_id`` is the number of the Paperless document of
which the PDF is a copy (§F/integrations/paperless/002528). An uploaded PDF has none.

Revision ID: e3f61a7c9b20
Revises: c7a94e12d5b3
Create Date: 2026-11-23 17:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e3f61a7c9b20"
down_revision: str | None = "c7a94e12d5b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.execute(
        "ALTER TABLE markdown_document ADD COLUMN IF NOT EXISTS paperless_document_id BIGINT"
    )


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    op.drop_column("markdown_document", "paperless_document_id")
