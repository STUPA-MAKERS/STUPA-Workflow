"""markdown_document: the PDFs that a protocol text embeds.

The upgrade adds the table ``markdown_document``. One row holds one checked PDF:
its object key ``media/documents/<id>``, its cleaned file name, its size and its
page count. The bytes live in the attachment bucket, never in the database.

Idempotent. A fresh database already gets the table from the ``create_all``
baseline (0001), and a migrated database gets it through ``CREATE TABLE IF NOT
EXISTS``.

The downgrade drops the table. The stored objects stay in the bucket, and the
references in the texts then print as missing.

Revision ID: 5b1e0c7d9a24
Revises: 20642e3b60c4
Create Date: 2026-11-13 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5b1e0c7d9a24"
down_revision: str | None = "20642e3b60c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS markdown_document (
        id uuid NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        storage_key text NOT NULL,
        name text NOT NULL,
        size bigint NOT NULL,
        pages integer NOT NULL,
        CONSTRAINT pk_markdown_document PRIMARY KEY (id),
        CONSTRAINT ck_markdown_document_size CHECK (size >= 0),
        CONSTRAINT ck_markdown_document_pages CHECK (pages > 0)
    )
    """,
)

_DOWNGRADE: tuple[str, ...] = ("DROP TABLE IF EXISTS markdown_document",)


def upgrade() -> None:
    """Add the table of the embedded PDFs."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Drop the table of the embedded PDFs."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
