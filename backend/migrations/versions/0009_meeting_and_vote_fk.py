"""livevote: meeting-Tabelle + vote.meeting_id-FK (T-16)

Revision ID: 0009_meeting_and_vote_fk
Revises: 0008_attachment_table
Create Date: 2026-06-06 00:00:09

Wie alle Modul-Tabellen entsteht ``meeting`` auf einem **frischen** Schema bereits
über ``Base.metadata.create_all`` in 0002 (Single-Source via ``app.models``) — inkl.
der nun am Modell deklarierten FK ``vote.meeting_id → meeting.id``. Für vor T-16
migrierte Schemata legt diese Revision die Tabelle **idempotent** nach
(``checkfirst``) und ergänzt die FK nur, falls sie noch fehlt (Inspector-Check).

Die Permission ``meeting.manage`` ist bereits in 0003 geseedet.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.models  # noqa: F401  — befüllt Base.metadata
from app.db import Base
from app.modules.livevote.models import Meeting

revision: str = "0009_meeting_and_vote_fk"
down_revision: str | None = "0008_attachment_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = "fk_vote_meeting_id_meeting"


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Meeting.__table__], checkfirst=True)

    inspector = sa.inspect(bind)
    existing = {fk.get("name") for fk in inspector.get_foreign_keys("vote")}
    referenced = {
        fk.get("referred_table") for fk in inspector.get_foreign_keys("vote")
    }
    if _FK_NAME not in existing and "meeting" not in referenced:
        op.create_foreign_key(
            _FK_NAME,
            "vote",
            "meeting",
            ["meeting_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {fk.get("name") for fk in inspector.get_foreign_keys("vote")}
    if _FK_NAME in existing:
        op.drop_constraint(_FK_NAME, "vote", type_="foreignkey")
    Base.metadata.drop_all(bind=bind, tables=[Meeting.__table__], checkfirst=True)
