"""budget HHJ-Stichtag pro Budget + HHJ nur als Jahr (Freitext-Label entfällt).

Idempotent (``IF [NOT] EXISTS`` / Constraint-Guards): bei frischer DB legt die
Baseline (``create_all`` aus den Modellen) die neuen Spalten/Constraints bereits an —
diese Migration ist dann ein No-op; bei bereits migrierten DBs trägt sie nach.

* ``budget.fiscal_start_month``/``fiscal_start_day`` — HHJ-Stichtag (Default 01.01.),
  nur am Top-Level fachlich relevant. Backfill aus dem Start-Datum eines bestehenden
  HHJ des Budgets (sonst Default 1/1).
* ``fiscal_year.year`` — Startjahr (ersetzt den Freitext ``label``). Backfill aus
  ``start_date``. ``label`` + dessen Unique-Constraint entfallen; neuer Unique-Key
  ``(budget_id, year)``.

Jede Anweisung als **eigenes** ``op.execute`` — asyncpg erlaubt keine Mehrfach-
Statements in einem Prepared Statement.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_budget_fiscal_stichtag"
down_revision: str | None = "0002_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    # 1. Budget-Stichtag (Tag/Monat des Periodenstarts), Default 01.01.
    "ALTER TABLE budget ADD COLUMN IF NOT EXISTS fiscal_start_month smallint NOT NULL DEFAULT 1",
    "ALTER TABLE budget ADD COLUMN IF NOT EXISTS fiscal_start_day smallint NOT NULL DEFAULT 1",
    """
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'budget_fiscal_start_month') THEN
            ALTER TABLE budget ADD CONSTRAINT budget_fiscal_start_month
                CHECK (fiscal_start_month BETWEEN 1 AND 12);
        END IF;
    END $$
    """,
    """
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'budget_fiscal_start_day') THEN
            ALTER TABLE budget ADD CONSTRAINT budget_fiscal_start_day
                CHECK (fiscal_start_day BETWEEN 1 AND 31);
        END IF;
    END $$
    """,
    # 2. HHJ als Jahr. Spalte + Backfill aus start_date, dann NOT NULL.
    "ALTER TABLE fiscal_year ADD COLUMN IF NOT EXISTS year integer",
    "UPDATE fiscal_year SET year = EXTRACT(YEAR FROM start_date)::int WHERE year IS NULL",
    "ALTER TABLE fiscal_year ALTER COLUMN year SET NOT NULL",
    # 3. Budget-Stichtag aus einem bestehenden HHJ-Start ableiten (sofern vorhanden).
    """
    UPDATE budget b
        SET fiscal_start_month = EXTRACT(MONTH FROM fy.start_date)::int,
            fiscal_start_day   = EXTRACT(DAY   FROM fy.start_date)::int
        FROM (
            SELECT DISTINCT ON (budget_id) budget_id, start_date
            FROM fiscal_year
            ORDER BY budget_id, start_date
        ) fy
        WHERE fy.budget_id = b.id
    """,
    # 4. Freitext-Label + alter Unique-Key entfernen; neuer Unique (budget_id, year).
    "ALTER TABLE fiscal_year DROP CONSTRAINT IF EXISTS uq_fiscal_year_budget_label",
    "ALTER TABLE fiscal_year DROP COLUMN IF EXISTS label",
    """
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'uq_fiscal_year_budget_year') THEN
            ALTER TABLE fiscal_year ADD CONSTRAINT uq_fiscal_year_budget_year
                UNIQUE (budget_id, year);
        END IF;
    END $$
    """,
)


_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE fiscal_year DROP CONSTRAINT IF EXISTS uq_fiscal_year_budget_year",
    "ALTER TABLE fiscal_year ADD COLUMN IF NOT EXISTS label text",
    "UPDATE fiscal_year SET label = year::text WHERE label IS NULL",
    "ALTER TABLE fiscal_year ALTER COLUMN label SET NOT NULL",
    """
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conname = 'uq_fiscal_year_budget_label') THEN
            ALTER TABLE fiscal_year ADD CONSTRAINT uq_fiscal_year_budget_label
                UNIQUE (budget_id, label);
        END IF;
    END $$
    """,
    "ALTER TABLE fiscal_year DROP COLUMN IF EXISTS year",
    "ALTER TABLE budget DROP CONSTRAINT IF EXISTS budget_fiscal_start_day",
    "ALTER TABLE budget DROP CONSTRAINT IF EXISTS budget_fiscal_start_month",
    "ALTER TABLE budget DROP COLUMN IF EXISTS fiscal_start_day",
    "ALTER TABLE budget DROP COLUMN IF EXISTS fiscal_start_month",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
