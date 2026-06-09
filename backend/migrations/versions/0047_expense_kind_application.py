"""budget_expense: add kind (expense|income) + application link (#25)

Revision ID: 0047_expense_kind_application
Revises: 0046_state_color
Create Date: 2026-06-09 21:00:00

Tatsächliche Ausgaben/Einnahmen (#25): ``budget_expense`` bekommt
* ``kind`` (``'expense'``|``'income'``) — Einnahmen erhöhen das verfügbare Budget,
  Ausgaben mindern es; CHECK ``budget_expense_kind_valid``.
* ``application_id`` (nullable FK → ``application`` ``ON DELETE SET NULL``) — eine an
  einen Antrag gebundene Ausgabe ersetzt dessen gebundenen Betrag anteilig. Mehrere
  Buchungen je Antrag erlaubt (kein UNIQUE). Index ``ix_budget_expense_application_id``.

Idempotent (Inspector-Check). ``down_revision`` = ``0046_state_color``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047_expense_kind_application"
down_revision: str | None = "0046_state_color"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("budget_expense")}
    if "kind" not in cols:
        op.add_column(
            "budget_expense",
            sa.Column(
                "kind", sa.Text(), nullable=False, server_default="expense"
            ),
        )
    # ``budget_expense`` wird in 0030 aus dem Live-Modell (``Base.metadata``) erzeugt,
    # auf einer frischen DB existiert die CHECK also schon. Der Inspector liefert den
    # **konventions-präfixierten** Namen (``ck_<table>_<name>``), darum hier exakt so
    # prüfen — sonst Doppel-Anlage ("constraint already exists").
    constraints = {c["name"] for c in insp.get_check_constraints("budget_expense")}
    if "ck_budget_expense_budget_expense_kind_valid" not in constraints:
        op.create_check_constraint(
            "budget_expense_kind_valid",
            "budget_expense",
            "kind IN ('expense', 'income')",
        )
    if "application_id" not in cols:
        op.add_column(
            "budget_expense",
            sa.Column(
                "application_id",
                sa.Uuid(),
                sa.ForeignKey("application.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    indexes = {i["name"] for i in insp.get_indexes("budget_expense")}
    if "ix_budget_expense_application_id" not in indexes:
        op.create_index(
            "ix_budget_expense_application_id",
            "budget_expense",
            ["application_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    indexes = {i["name"] for i in insp.get_indexes("budget_expense")}
    if "ix_budget_expense_application_id" in indexes:
        op.drop_index("ix_budget_expense_application_id", "budget_expense")
    cols = {c["name"] for c in insp.get_columns("budget_expense")}
    if "application_id" in cols:
        op.drop_column("budget_expense", "application_id")
    constraints = {c["name"] for c in insp.get_check_constraints("budget_expense")}
    if "ck_budget_expense_budget_expense_kind_valid" in constraints:
        op.drop_constraint(
            "ck_budget_expense_budget_expense_kind_valid",
            "budget_expense",
            type_="check",
        )
    if "kind" in cols:
        op.drop_column("budget_expense", "kind")
