"""deadline_policy — benannte Frist-Registry (Named Deadline Policies)

Revision ID: 0037_deadline_policy
Revises: 0036_agenda_body
Create Date: 2026-06-09 00:00:37

Eine Policy ist ``absolute`` (fixes Datum, pro Semester pflegbar) oder relativ
(``relative_submitted``/``relative_changed`` = Antrags-Zeitpunkt + ``offset_days``).
Der Flow referenziert sie über ``key``. Idempotent (Inspector-Check).
``down_revision`` = ``0036_agenda_body``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0037_deadline_policy"
down_revision: str | None = "0036_agenda_body"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "deadline_policy" in set(insp.get_table_names()):
        return
    op.create_table(
        "deadline_policy",
        sa.Column(
            "id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("label", JSONB(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("absolute_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offset_days", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('absolute','relative_submitted','relative_changed')",
            name="deadline_policy_kind",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "deadline_policy" in set(insp.get_table_names()):
        op.drop_table("deadline_policy")
