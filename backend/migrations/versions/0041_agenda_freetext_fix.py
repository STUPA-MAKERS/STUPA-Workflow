"""Reconcile meeting_agenda_item for freetext TOPs (title + nullable application_id)

Revision ID: 0041_agenda_freetext_fix
Revises: 0040_sessions_rework
Create Date: 2026-06-09 15:00:00

Bestands-Schemata, deren ``meeting_agenda_item`` noch über ``create_all`` (vor den
Freitext-TOP-Modelländerungen) entstand, fehlt die ``title``-Spalte und ihr
``application_id`` ist fälschlich ``NOT NULL`` — Freitext-TOPs (ohne Antrag) lassen
sich dort nicht anlegen (NOT-NULL-Verletzung). Migration 0033 übersprang die Tabelle
idempotent, wenn sie bereits existierte, und reparierte das nie. Hier nachgezogen,
idempotent über den Inspector. ``down_revision`` = ``0040_sessions_rework``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041_agenda_freetext_fix"
down_revision: str | None = "0040_sessions_rework"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "meeting_agenda_item" not in set(insp.get_table_names()):
        return
    cols = {c["name"]: c for c in insp.get_columns("meeting_agenda_item")}
    if "title" not in cols:
        op.add_column(
            "meeting_agenda_item", sa.Column("title", sa.Text(), nullable=True)
        )
    if "application_id" in cols and not cols["application_id"]["nullable"]:
        op.alter_column(
            "meeting_agenda_item",
            "application_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )


def downgrade() -> None:
    # Nicht eindeutig invertierbar (Bestands-Drift); bewusst no-op.
    pass
