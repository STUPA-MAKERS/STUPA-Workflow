"""meeting_agenda_item — Tagesordnung (Antrag ↔ Sitzung) (#10/#58)

Revision ID: 0033_meeting_agenda
Revises: 0032_meeting_attendance
Create Date: 2026-06-09 00:00:33

Geordnete Zuordnung von Anträgen zu einer Sitzung (Tagesordnung): Quelle der
Protokoll-TOPs und der zugeordneten Abstimmungen. Idempotent (Inspector-Check).
``down_revision`` = ``0032_meeting_attendance``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_meeting_agenda"
down_revision: str | None = "0032_meeting_attendance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "meeting_agenda_item" in set(insp.get_table_names()):
        return
    op.create_table(
        "meeting_agenda_item",
        sa.Column(
            "id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "meeting_id",
            sa.Uuid(),
            sa.ForeignKey("meeting.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("application.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "meeting_id", "application_id", name="uq_agenda_meeting_application"
        ),
    )
    op.create_index("ix_agenda_meeting", "meeting_agenda_item", ["meeting_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "meeting_agenda_item" in set(insp.get_table_names()):
        op.drop_table("meeting_agenda_item")
