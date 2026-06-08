"""meeting_attendance — Anwesenheit je Sitzung/Mitglied (#Meetings/#55/#56)

Revision ID: 0032_meeting_attendance
Revises: 0031_forced_gremium_roles
Create Date: 2026-06-09 00:00:32

Anwesenheits-Erfassung: ein Eintrag je (Sitzung, Mitglied), Status present/
excused/absent, ``source`` self/lead. Idempotent (Inspector-Check).
``down_revision`` = ``0031_forced_gremium_roles``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_meeting_attendance"
down_revision: str | None = "0031_forced_gremium_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "meeting_attendance" in set(insp.get_table_names()):
        return
    op.create_table(
        "meeting_attendance",
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
            "principal_id",
            sa.Uuid(),
            sa.ForeignKey("principal.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), server_default="lead", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "meeting_id", "principal_id", name="uq_attendance_meeting_principal"
        ),
        sa.CheckConstraint(
            "status IN ('present','excused','absent')", name="attendance_status"
        ),
        sa.CheckConstraint("source IN ('self','lead')", name="attendance_source"),
    )
    op.create_index("ix_attendance_meeting", "meeting_attendance", ["meeting_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "meeting_attendance" in set(insp.get_table_names()):
        op.drop_table("meeting_attendance")
