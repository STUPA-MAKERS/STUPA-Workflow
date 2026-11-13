"""Haushaltsplan: a plan on the agenda is an Anlage of the protocol.

``budget_plan_vote_snapshot`` keeps the file of a plan version as it was when a vote
on it opened. ``meeting_agenda_item`` gets ``plan_document_id``, the PDF that the
protocol appends.

Idempotent. A fresh database already has both from the ``create_all`` baseline
(0001), because the models sit in ``app.models``.

Revision ID: 7e2a4c91b0d6
Revises: 9c4d1e7a52b3
Create Date: 2026-11-13 22:20:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "7e2a4c91b0d6"
down_revision: str | None = "9c4d1e7a52b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the snapshot table and add the document of an agenda item."""
    op.execute(
        "CREATE TABLE IF NOT EXISTS budget_plan_vote_snapshot ("
        "vote_id uuid NOT NULL "
        "CONSTRAINT fk_budget_plan_vote_snapshot_vote_id_vote "
        "REFERENCES vote (id) ON DELETE CASCADE, "
        "document jsonb NOT NULL, "
        "created_at timestamptz NOT NULL DEFAULT now(), "
        "CONSTRAINT pk_budget_plan_vote_snapshot PRIMARY KEY (vote_id))"
    )
    op.execute(
        "ALTER TABLE meeting_agenda_item ADD COLUMN IF NOT EXISTS plan_document_id uuid "
        "CONSTRAINT fk_meeting_agenda_item_plan_document_id_markdown_document "
        "REFERENCES markdown_document (id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    """Drop the document of an agenda item and the snapshot table."""
    op.execute("ALTER TABLE meeting_agenda_item DROP COLUMN IF EXISTS plan_document_id")
    op.execute("DROP TABLE IF EXISTS budget_plan_vote_snapshot")
