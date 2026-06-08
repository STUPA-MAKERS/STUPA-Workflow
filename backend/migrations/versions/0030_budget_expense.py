"""budget_expense — eigenständige Ausgaben gegen eine Kostenstelle (#25)

Revision ID: 0030_budget_expense
Revises: 0029_gremium_role_id_default
Create Date: 2026-06-09 00:00:30

Direkte Buchungen ohne Antrag (Barauslage/Rechnung) gegen ``budget`` + ``fiscal_year``.
Zählt im Roll-up als gebundener Verbrauch. Tabelle entsteht — wie alle Modul-Tabellen
— über ``Base.metadata.create_all`` (0002); für bereits migrierte Schemata legt diese
Revision sie **idempotent** (``checkfirst``) nach.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import app.models  # noqa: F401  — befüllt Base.metadata
from app.db import Base

revision: str = "0030_budget_expense"
down_revision: str | None = "0029_gremium_role_id_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [Base.metadata.tables["budget_expense"]]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=_TABLES, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=_TABLES, checkfirst=True)
