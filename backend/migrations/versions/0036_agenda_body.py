"""meeting_agenda_item.body — Markdown-Text je TOP (#58)

Revision ID: 0036_agenda_body
Revises: 0035_vote_question
Create Date: 2026-06-09 00:00:36

Pro-TOP-Editor: jeder Tagesordnungspunkt trägt seinen eigenen Markdown-Text, der
ins finale Protokoll assembliert wird. Idempotent (Inspector-Check).
``down_revision`` = ``0035_vote_question``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_agenda_body"
down_revision: str | None = "0035_vote_question"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("meeting_agenda_item")}
    if "body" not in cols:
        op.add_column(
            "meeting_agenda_item", sa.Column("body", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("meeting_agenda_item")}
    if "body" in cols:
        op.drop_column("meeting_agenda_item", "body")
