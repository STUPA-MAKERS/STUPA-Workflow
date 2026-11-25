"""Antragsart: the signature rows of the Antrag PDF (spec 003005).

``application_type`` gets ``signature_rows``. Every existing type gets the two rows that
the PDF showed before the rows became a setting, so an existing PDF does not change. A new
type starts with an empty list.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001); the update then fills only the rows that are still empty.

Revision ID: 5b8e2f71c9a4
Revises: 1cab2fdfd7ea
Create Date: 2026-11-24 22:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b8e2f71c9a4"
down_revision: str | None = "1cab2fdfd7ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROWS = (
    '[{"label": "Sachlich richtig", "signer": "Finanzreferent:in"}, '
    '{"label": "Ausführungsermächtigt", "signer": "Haushaltsbeauftragte:r"}]'
)


def upgrade() -> None:
    """Add the rows and give every existing type the two former rows."""
    op.execute(
        "ALTER TABLE application_type "
        "ADD COLUMN IF NOT EXISTS signature_rows jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        sa.text(
            "UPDATE application_type SET signature_rows = CAST(:rows AS jsonb) "
            "WHERE signature_rows = '[]'::jsonb"
        ).bindparams(rows=_ROWS)
    )


def downgrade() -> None:
    """Drop the rows."""
    op.execute("ALTER TABLE application_type DROP COLUMN IF EXISTS signature_rows")
