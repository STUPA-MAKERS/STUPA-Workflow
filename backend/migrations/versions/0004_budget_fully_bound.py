"""budget: Flag »komplett gebunden« je Kostenstelle.

Idempotent (``IF NOT EXISTS``): frische DBs erhalten die Spalte bereits aus
``create_all`` (Baseline) — dann No-op; migrierte DBs tragen sie nach.

``budget.fully_bound`` = die gesamte Zuteilung der Kostenstelle (inkl. Unterbaum)
gilt je HHJ als gebunden (committed = allocated, verfügbar 0).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_budget_fully_bound"
down_revision: str | None = "0003_budget_fiscal_stichtag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE budget ADD COLUMN IF NOT EXISTS fully_bound boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE budget DROP COLUMN IF EXISTS fully_bound")
