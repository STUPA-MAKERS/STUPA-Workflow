"""Haushaltsplan: side and plan switch of a cost center, plan tables.

1. ``budget`` gets ``side`` ('income' or 'expense'), and ``plan_enabled`` (the plan
   switch, off for every existing row).
2. ``budget_plan`` is the Haushaltsplan of one fiscal year. ``budget_plan_version``
   holds the Stammplan (number 0) and each Nachtrag with its state. Two partial
   unique indexes keep at most one version in force and at most one version before
   ``in_force`` per plan. ``budget_plan_line`` holds the
   Ansatz, the Erläuterung and the Vermerke of one cost center in one version.
   ``budget_plan_step`` holds the ordered steps that a plan version of a top-level
   cost center passes.
3. ``budget`` loses ``hidden_in_budget``. A hidden cost center becomes inactive
   first, because the switch Aktiv now is the one way to hide it.
4. ``vote`` gets ``plan_version_id``: the plan version that a vote of a step decides.

No plan data moves: an existing fiscal year gets its Stammplan when a person sets the
plan switch of its top-level cost center to on.

Idempotent. A fresh database already gets the columns and the tables from the
``create_all`` baseline (0001), because the models sit in ``app.models``. A migrated
database gets them through ``IF NOT EXISTS``.

Revision ID: 8d53b821d874
Revises: 3d95c7b1f9e6
Create Date: 2026-11-12 17:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "8d53b821d874"
down_revision: str | None = "3d95c7b1f9e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _constraint(table: str, name: str, definition: str) -> str:
    """Return the statement that adds a constraint when the table does not have it."""
    return f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conrelid = '{table}'::regclass AND conname = '{name}'
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} {definition};
            END IF;
        END $$
        """


_UPGRADE: tuple[str, ...] = (
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_name = 'budget' AND column_name = 'hidden_in_budget'
        ) THEN
            UPDATE budget SET active = false WHERE hidden_in_budget;
        END IF;
    END $$
    """,
    "ALTER TABLE budget DROP COLUMN IF EXISTS hidden_in_budget",
    "ALTER TABLE budget ADD COLUMN IF NOT EXISTS side text",
    "ALTER TABLE budget ADD COLUMN IF NOT EXISTS plan_enabled boolean NOT NULL DEFAULT false",
    _constraint("budget", "ck_budget_budget_side", "CHECK (side IN ('income', 'expense'))"),
    """
    CREATE TABLE IF NOT EXISTS budget_plan (
        id uuid NOT NULL DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        fiscal_year_id uuid NOT NULL,
        CONSTRAINT pk_budget_plan PRIMARY KEY (id),
        CONSTRAINT fk_budget_plan_fiscal_year_id_fiscal_year
            FOREIGN KEY (fiscal_year_id) REFERENCES fiscal_year (id) ON DELETE CASCADE,
        CONSTRAINT uq_budget_plan_fiscal_year_id UNIQUE (fiscal_year_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS budget_plan_version (
        id uuid NOT NULL DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        plan_id uuid NOT NULL,
        number integer NOT NULL,
        state text NOT NULL DEFAULT 'draft',
        in_force_at timestamptz,
        steps jsonb NOT NULL DEFAULT '[]'::jsonb,
        CONSTRAINT pk_budget_plan_version PRIMARY KEY (id),
        CONSTRAINT fk_budget_plan_version_plan_id_budget_plan
            FOREIGN KEY (plan_id) REFERENCES budget_plan (id) ON DELETE CASCADE,
        CONSTRAINT uq_budget_plan_version_plan_id_number UNIQUE (plan_id, number),
        CONSTRAINT ck_budget_plan_version_budget_plan_version_number CHECK (number >= 0),
        CONSTRAINT ck_budget_plan_version_budget_plan_version_state
            CHECK (state IN ('draft', 'in_progress', 'in_force', 'replaced'))
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_budget_plan_version_in_force
        ON budget_plan_version (plan_id) WHERE state = 'in_force'
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_budget_plan_version_open
        ON budget_plan_version (plan_id) WHERE state IN ('draft', 'in_progress')
    """,
    """
    CREATE TABLE IF NOT EXISTS budget_plan_line (
        id uuid NOT NULL DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        version_id uuid NOT NULL,
        budget_id uuid NOT NULL,
        amount numeric(12, 2) NOT NULL DEFAULT 0,
        note text,
        name text,
        path_key text,
        transferable boolean NOT NULL DEFAULT false,
        coverable boolean NOT NULL DEFAULT false,
        blocked numeric(12, 2) NOT NULL DEFAULT 0,
        CONSTRAINT pk_budget_plan_line PRIMARY KEY (id),
        CONSTRAINT fk_budget_plan_line_version_id_budget_plan_version
            FOREIGN KEY (version_id) REFERENCES budget_plan_version (id) ON DELETE CASCADE,
        CONSTRAINT fk_budget_plan_line_budget_id_budget
            FOREIGN KEY (budget_id) REFERENCES budget (id) ON DELETE CASCADE,
        CONSTRAINT uq_budget_plan_line_version_id_budget_id UNIQUE (version_id, budget_id),
        CONSTRAINT ck_budget_plan_line_budget_plan_line_amount CHECK (amount >= 0),
        CONSTRAINT ck_budget_plan_line_budget_plan_line_blocked
            CHECK (blocked >= 0 AND blocked <= amount)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_budget_plan_line_budget_id ON budget_plan_line (budget_id)",
    """
    CREATE TABLE IF NOT EXISTS budget_plan_step (
        id uuid NOT NULL DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        budget_id uuid NOT NULL,
        position integer NOT NULL,
        name text NOT NULL,
        gremium_id uuid,
        CONSTRAINT pk_budget_plan_step PRIMARY KEY (id),
        CONSTRAINT fk_budget_plan_step_budget_id_budget
            FOREIGN KEY (budget_id) REFERENCES budget (id) ON DELETE CASCADE,
        CONSTRAINT fk_budget_plan_step_gremium_id_gremium
            FOREIGN KEY (gremium_id) REFERENCES gremium (id) ON DELETE SET NULL,
        CONSTRAINT uq_budget_plan_step_budget_id_position UNIQUE (budget_id, position),
        CONSTRAINT ck_budget_plan_step_budget_plan_step_position CHECK (position >= 0)
    )
    """,
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS plan_version_id uuid",
    _constraint(
        "vote",
        "fk_vote_plan_version_id_budget_plan_version",
        "FOREIGN KEY (plan_version_id) REFERENCES budget_plan_version (id) ON DELETE SET NULL",
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE vote DROP COLUMN IF EXISTS plan_version_id",
    "DROP TABLE IF EXISTS budget_plan_step",
    "DROP TABLE IF EXISTS budget_plan_line",
    "DROP TABLE IF EXISTS budget_plan_version",
    "DROP TABLE IF EXISTS budget_plan",
    "ALTER TABLE budget DROP CONSTRAINT IF EXISTS ck_budget_budget_side",
    "ALTER TABLE budget DROP COLUMN IF EXISTS plan_enabled",
    "ALTER TABLE budget DROP COLUMN IF EXISTS side",
    "ALTER TABLE budget ADD COLUMN IF NOT EXISTS hidden_in_budget boolean NOT NULL DEFAULT false",
)


def upgrade() -> None:
    """Add the plan columns of ``budget`` and create the plan tables."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the plan tables and the plan columns of ``budget``."""
    for statement in _DOWNGRADE:
        op.execute(statement)
