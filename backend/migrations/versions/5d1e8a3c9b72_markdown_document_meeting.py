"""Embedded PDFs: store the Sitzung of each PDF.

The upgrade adds `markdown_document.meeting_id` with its index. The read of an embedded
PDF needs the read right of its Sitzung (§NF/security/files/000979), so each row that
exists gets the Sitzung of the text that refers to it:

- the PDF of a Haushaltsplan from `meeting_agenda_item.plan_document_id`,
- an uploaded PDF from the agenda item body or the protocol text that holds its id.

A PDF that no text refers to keeps NULL and is readable only through the public route
of a public protocol. Idempotent. The downgrade drops the index and the column.

Revision ID: 5d1e8a3c9b72
Revises: c4f9a2e6d815
Create Date: 2026-11-15 23:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5d1e8a3c9b72"
down_revision: str | None = "c4f9a2e6d815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_markdown_document_meeting_id_meeting"


def upgrade() -> None:
    """Add the column and the index, then fill the column from the texts."""
    op.execute("ALTER TABLE markdown_document ADD COLUMN IF NOT EXISTS meeting_id uuid")
    op.execute(f"ALTER TABLE markdown_document DROP CONSTRAINT IF EXISTS {_FK}")
    op.execute(
        f"ALTER TABLE markdown_document ADD CONSTRAINT {_FK} "
        "FOREIGN KEY (meeting_id) REFERENCES meeting (id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_markdown_document_meeting "
        "ON markdown_document (meeting_id)"
    )
    op.execute(
        "UPDATE markdown_document d SET meeting_id = i.meeting_id "
        "FROM meeting_agenda_item i "
        "WHERE d.meeting_id IS NULL AND i.plan_document_id = d.id"
    )
    op.execute(
        "UPDATE markdown_document d SET meeting_id = i.meeting_id "
        "FROM meeting_agenda_item i "
        "WHERE d.meeting_id IS NULL AND i.body IS NOT NULL "
        "AND position(d.id::text in i.body) > 0"
    )
    op.execute(
        "UPDATE markdown_document d SET meeting_id = p.meeting_id "
        "FROM protocol p "
        "WHERE d.meeting_id IS NULL AND position(d.id::text in p.markdown) > 0"
    )


def downgrade() -> None:
    """Drop the index and the column."""
    op.execute("DROP INDEX IF EXISTS ix_markdown_document_meeting")
    op.execute("ALTER TABLE markdown_document DROP COLUMN IF EXISTS meeting_id")
