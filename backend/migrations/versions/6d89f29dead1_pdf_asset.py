"""The PDF branding: export logo and footer graphic (specs 000891, 000892).

pdf_asset holds one row per slot (``logo``, ``footer``). It replaces export_logo: the
upgrade copies an uploaded export logo into the slot ``logo`` and drops export_logo.
Then it seeds the built-in STUPA logo and the Skyline into each slot that is still
empty, so the PDFs keep their look until the admin changes it.

Idempotent. A fresh database already has pdf_asset from the ``create_all`` baseline
(0001), and export_logo from edaeff27b6a4, which is empty there.

Revision ID: 6d89f29dead1
Revises: edaeff27b6a4
Create Date: 2026-11-14 01:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "6d89f29dead1"
down_revision: str | None = "edaeff27b6a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create pdf_asset, move the export logo over and seed the built-in graphics."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pdf_asset (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at timestamptz NOT NULL DEFAULT now(),
            slot text NOT NULL,
            builtin text,
            object_key text,
            file_name text,
            mime text,
            size integer,
            created_by text,
            CONSTRAINT uq_pdf_asset_slot UNIQUE (slot),
            CONSTRAINT ck_pdf_asset_slot CHECK (slot IN ('logo', 'footer')),
            CONSTRAINT ck_pdf_asset_source CHECK ((builtin IS NULL) <> (object_key IS NULL))
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('export_logo') IS NOT NULL THEN
                INSERT INTO pdf_asset
                    (created_at, slot, object_key, file_name, mime, size, created_by)
                SELECT created_at, 'logo', object_key, file_name, mime, size, created_by
                FROM export_logo
                ON CONFLICT (slot) DO NOTHING;
                DROP TABLE export_logo;
            END IF;
        END $$
        """
    )
    op.execute(
        """
        INSERT INTO pdf_asset (slot, builtin)
        VALUES ('logo', 'STUPA'), ('footer', 'Skyline')
        ON CONFLICT (slot) DO NOTHING
        """
    )


def downgrade() -> None:
    """Move an uploaded export logo back to export_logo and drop pdf_asset."""
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
        INSERT INTO export_logo (created_at, object_key, file_name, mime, size, created_by)
        SELECT created_at, object_key, file_name, mime, size, created_by
        FROM pdf_asset WHERE slot = 'logo' AND object_key IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute("DROP TABLE IF EXISTS pdf_asset")
