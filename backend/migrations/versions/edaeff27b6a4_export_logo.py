"""The export logo of the branding (spec 000891).

export_logo holds at most one row: the logo of every exported PDF except the
protocol. The bytes live in the object storage.

The upgrade also drops the key ``logos.export`` from every stored branding, because the
export logo was an inline branding logo on the development branch before, and the
``Branding`` schema now refuses that key.

Idempotent. A fresh database already has the table from the ``create_all`` baseline
(0001).

Revision ID: edaeff27b6a4
Revises: 4b8e2f6c1a93
Create Date: 2026-11-14 00:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "edaeff27b6a4"
down_revision: str | None = "4b8e2f6c1a93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the table and drop the old inline export logo from the branding."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS export_logo (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at timestamptz NOT NULL DEFAULT now(),
            singleton boolean NOT NULL DEFAULT true,
            object_key text NOT NULL,
            file_name text NOT NULL,
            mime text NOT NULL,
            size integer NOT NULL,
            created_by text,
            CONSTRAINT uq_export_logo_singleton UNIQUE (singleton),
            CONSTRAINT ck_export_logo_singleton CHECK (singleton)
        )
        """
    )
    op.execute(
        """
        UPDATE site_config_version
        SET branding = jsonb_set(branding, '{logos}', (branding -> 'logos') - 'export')
        WHERE branding -> 'logos' ? 'export'
        """
    )


def downgrade() -> None:
    """Drop the table."""
    op.execute("DROP TABLE IF EXISTS export_logo")
