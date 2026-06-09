"""vote.question — Beschlussfrage einer (Live-)Abstimmung (#Meetings)

Revision ID: 0035_vote_question
Revises: 0033_meeting_agenda
Create Date: 2026-06-09 00:00:34

Eine optionale Abstimmungsfrage (»Worüber wird abgestimmt?«), die im Protokoll
am Abstimmungs-Snippet ausgewiesen wird. Idempotent (Inspector-Check).
``down_revision`` = ``0033_meeting_agenda``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_vote_question"
down_revision: str | None = "0034_application_created_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("vote")}
    if "question" not in cols:
        op.add_column("vote", sa.Column("question", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("vote")}
    if "question" in cols:
        op.drop_column("vote", "question")
