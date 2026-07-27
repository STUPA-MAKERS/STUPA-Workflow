"""Budget: a fiscal-year start date per budget, and the fiscal year as a year only.

Idempotent through `IF [NOT] EXISTS` and constraint guards. On a fresh database the
baseline (`create_all` from the models) already adds the new columns and constraints,
so this migration is a no-op there. On an already migrated database it adds them.

* `budget.fiscal_start_month` and `fiscal_start_day`: the start date of the fiscal
  year (default January 1). It matters only at the top level. The backfill reads the
  start date of an existing fiscal year of the budget, else it keeps the default 1/1.
* `fiscal_year.year`: the start year. It replaces the free-text `label`. The backfill
  reads `start_date`. `label` and its unique constraint go away. The new unique key is
  `(budget_id, year)`.

Every statement needs its own `op.execute`. asyncpg does not accept several statements
in one prepared statement.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_budget_fiscal_stichtag"
down_revision: str | None = "0002_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
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
    "ALTER TABLE fiscal_year ADD COLUMN IF NOT EXISTS year integer",
    "UPDATE fiscal_year SET year = EXTRACT(YEAR FROM start_date)::int WHERE year IS NULL",
    "ALTER TABLE fiscal_year ALTER COLUMN year SET NOT NULL",
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
