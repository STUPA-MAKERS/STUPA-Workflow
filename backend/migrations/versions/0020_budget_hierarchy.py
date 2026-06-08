"""budget: hierarchischer Kostenstellen-Baum + Haushaltsjahre (CR #76/#78, R7.1*)

Revision ID: 0020_budget_hierarchy
Revises: 0019_seed_application_manage
Create Date: 2026-06-08 00:00:20

Ergänzt das flache ``budget_pot``-Modell (T-17) um den **Kostenstellen-Baum**:

* Tabellen ``budget`` (Self-FK-Baum + ``path_key``), ``fiscal_year`` (HHJ je
  Top-Budget, disjunkt) und ``budget_allocation`` (Top-Down-Zuteilung Budget × HHJ).
  Sie entstehen — wie alle Modul-Tabellen — über ``Base.metadata.create_all`` (0002);
  für bereits migrierte Schemata legt diese Revision sie **idempotent**
  (``checkfirst``) nach.
* Spalten ``application.budget_id`` (FK→budget) + ``application.fiscal_year_id``
  (FK→fiscal_year) inkl. Indizes — idempotent (Inspector-Guard), da ``create_all`` auf
  frischen DBs bereits die volle ``application``-Tabelle inkl. dieser Spalten anlegt.
* MV ``mv_budget_rollup`` (gebundene Summe je Knoten × HHJ): Roll-up der genehmigten
  Antrags-Beträge von Leaf zu allen Vorfahren über das ``path_key``-Präfix (R7.1c,
  data-model §3). Unique-Index für ``REFRESH … CONCURRENTLY`` (Worker).

Lineare Kette: ``down_revision`` = ``0019_seed_application_manage`` → ``alembic heads`` = EIN Head.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.models  # noqa: F401  — befüllt Base.metadata
from app.db import Base

revision: str = "0020_budget_hierarchy"
down_revision: str | None = "0019_seed_application_manage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [
    Base.metadata.tables["budget"],
    Base.metadata.tables["fiscal_year"],
    Base.metadata.tables["budget_allocation"],
]

# Antrag → Kostenstelle/HHJ. Idempotent: (Spalte, Index).
_APP_COLUMNS = (
    ("budget_id", "ix_application_budget_id", "budget"),
    ("fiscal_year_id", "ix_application_fiscal_year_id", "fiscal_year"),
)

# Roll-up der gebundenen Summe: jeder genehmigte Antrag zählt zu seiner Kostenstelle
# (``b.path_key = leaf.path_key``) und allen Vorfahren (``leaf.path_key LIKE b.path_key||'-%'``).
# Der ``-``-Trenner verhindert Präfix-Fehltreffer (``VS`` matcht nicht ``VST-…``).
_MV_ROLLUP = """
CREATE MATERIALIZED VIEW mv_budget_rollup AS
SELECT b.id              AS budget_id,
       a.fiscal_year_id  AS fiscal_year_id,
       COALESCE(SUM(a.amount), 0) AS committed
FROM application a
JOIN budget leaf ON leaf.id = a.budget_id
JOIN budget b
  ON b.path_key = leaf.path_key
  OR leaf.path_key LIKE b.path_key || '-%'
JOIN budget_entry be
  ON be.application_id = a.id
 AND be.stage IN ('reserved', 'approved', 'paid')
WHERE a.amount IS NOT NULL
  AND a.fiscal_year_id IS NOT NULL
GROUP BY b.id, a.fiscal_year_id
WITH DATA
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=_TABLES, checkfirst=True)

    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("application")}
    existing_idx = {i["name"] for i in inspector.get_indexes("application")}
    for column, index, referred in _APP_COLUMNS:
        if column not in existing_cols:
            op.add_column(
                "application",
                sa.Column(
                    column,
                    sa.Uuid,
                    sa.ForeignKey(f"{referred}.id"),
                    nullable=True,
                ),
            )
        if index not in existing_idx:
            op.create_index(index, "application", [column])

    op.execute(_MV_ROLLUP)
    op.execute(
        "CREATE UNIQUE INDEX uq_mv_budget_rollup "
        "ON mv_budget_rollup (budget_id, fiscal_year_id)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_budget_rollup")

    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("application")}
    existing_idx = {i["name"] for i in inspector.get_indexes("application")}
    for column, index, _referred in _APP_COLUMNS:
        if index in existing_idx:
            op.drop_index(index, table_name="application")
        if column in existing_cols:
            op.drop_column("application", column)

    Base.metadata.drop_all(bind=bind, tables=_TABLES, checkfirst=True)
