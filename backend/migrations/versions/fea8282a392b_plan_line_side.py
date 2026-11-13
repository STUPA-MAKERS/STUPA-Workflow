"""Haushaltsplan: the side moves to the plan line, each plan starts as a draft.

1. ``budget_plan_line`` gets ``side`` ('income' or 'expense'). The line of a Titel, a
   direct child of a top-level cost center, takes the side of its cost center.
   ``budget`` then loses ``side``, because the plan of a year says which Titel are
   income and which are expenses.
2. A Haushaltsplan that only the plan switch made goes back to a draft: its one
   version is the first one, is in force, passed no step and belongs to an open fiscal
   year. The allocations stay as they are.
3. Each open fiscal year of a top-level cost center with the plan switch on that has no
   Haushaltsplan gets one with a draft version. The Ansatz of a cost center without a
   child is its allocation, and a parent holds the sum of its children. A closed fiscal
   year gets none, because it refuses plan changes.
4. The role ``admin`` gets the permission ``budget.plan.set_state``.

The upgrade writes no audit entry: it changes the form of the data and decides nothing.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001) and has no ``budget.side``, so the copy runs only when that column exists.

One-way: the downgrade restores the column ``budget.side`` from the lines of the newest
version of each plan. The plans that went back to a draft stay drafts.

Revision ID: fea8282a392b
Revises: 8d53b821d874
Create Date: 2026-11-13 15:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "fea8282a392b"
down_revision: str | None = "8d53b821d874"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The versions that only the plan switch made: the one version of their plan, in force
#: without a step, in an open fiscal year.
_SWITCH_MADE = """
    SELECT v.id
      FROM budget_plan_version v
      JOIN budget_plan p ON p.id = v.plan_id
      JOIN fiscal_year fy ON fy.id = p.fiscal_year_id
     WHERE v.number = 0
       AND v.state = 'in_force'
       AND v.steps = '[]'::jsonb
       AND fy.closed_at IS NULL
       AND NOT EXISTS (
           SELECT 1 FROM budget_plan_version o WHERE o.plan_id = v.plan_id AND o.id <> v.id
       )
"""

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE budget_plan_line ADD COLUMN IF NOT EXISTS side text",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid = 'budget_plan_line'::regclass
               AND conname = 'ck_budget_plan_line_budget_plan_line_side'
        ) THEN
            ALTER TABLE budget_plan_line
                ADD CONSTRAINT ck_budget_plan_line_budget_plan_line_side
                CHECK (side IN ('income', 'expense'));
        END IF;
    END $$
    """,
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_name = 'budget' AND column_name = 'side'
        ) THEN
            UPDATE budget_plan_line l
               SET side = b.side
              FROM budget b
              JOIN budget top ON top.id = b.parent_id
             WHERE l.budget_id = b.id AND top.parent_id IS NULL;
        END IF;
    END $$
    """,
    "ALTER TABLE budget DROP CONSTRAINT IF EXISTS ck_budget_budget_side",
    "ALTER TABLE budget DROP COLUMN IF EXISTS side",
    f"""
    UPDATE budget_plan_line SET name = NULL, path_key = NULL
     WHERE version_id IN ({_SWITCH_MADE})
    """,
    f"""
    UPDATE budget_plan_version SET state = 'draft', in_force_at = NULL
     WHERE id IN (SELECT id FROM ({_SWITCH_MADE}) AS made)
    """,
    """
    WITH RECURSIVE years AS (
        SELECT fy.id AS fiscal_year_id, top.id AS top_id
          FROM fiscal_year fy
          JOIN budget top ON top.id = fy.budget_id
         WHERE top.parent_id IS NULL
           AND top.plan_enabled
           AND fy.closed_at IS NULL
           AND NOT EXISTS (SELECT 1 FROM budget_plan p WHERE p.fiscal_year_id = fy.id)
    ),
    plans AS (
        INSERT INTO budget_plan (id, fiscal_year_id)
        SELECT gen_random_uuid(), fiscal_year_id FROM years
        RETURNING id, fiscal_year_id
    ),
    versions AS (
        INSERT INTO budget_plan_version (id, plan_id, number, state)
        SELECT gen_random_uuid(), id, 0, 'draft' FROM plans
        RETURNING id, plan_id
    ),
    below AS (
        SELECT b.id AS node_id, b.id AS leaf_id
          FROM budget b
         WHERE b.parent_id IS NOT NULL
        UNION ALL
        SELECT below.node_id, child.id
          FROM below
          JOIN budget child ON child.parent_id = below.leaf_id
    ),
    leaves AS (
        SELECT below.node_id, below.leaf_id
          FROM below
         WHERE NOT EXISTS (SELECT 1 FROM budget c WHERE c.parent_id = below.leaf_id)
    ),
    tree AS (
        SELECT years.fiscal_year_id, b.id AS node_id
          FROM years
          JOIN budget b ON b.parent_id = years.top_id
        UNION ALL
        SELECT tree.fiscal_year_id, child.id
          FROM tree
          JOIN budget child ON child.parent_id = tree.node_id
    )
    INSERT INTO budget_plan_line (id, version_id, budget_id, amount)
    SELECT gen_random_uuid(), versions.id, tree.node_id, COALESCE(SUM(a.allocated), 0)
      FROM tree
      JOIN plans ON plans.fiscal_year_id = tree.fiscal_year_id
      JOIN versions ON versions.plan_id = plans.id
      JOIN leaves ON leaves.node_id = tree.node_id
      LEFT JOIN budget_allocation a
        ON a.budget_id = leaves.leaf_id AND a.fiscal_year_id = tree.fiscal_year_id
     GROUP BY versions.id, tree.node_id
    """,
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'budget.plan.set_state' FROM role r WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'budget.plan.set_state'",
    "ALTER TABLE budget ADD COLUMN IF NOT EXISTS side text",
    """
    UPDATE budget b
       SET side = newest.side
      FROM (
          SELECT DISTINCT ON (l.budget_id) l.budget_id, l.side
            FROM budget_plan_line l
            JOIN budget_plan_version v ON v.id = l.version_id
           WHERE l.side IS NOT NULL
           ORDER BY l.budget_id, v.created_at DESC
      ) AS newest
     WHERE b.id = newest.budget_id
    """,
    """
    ALTER TABLE budget ADD CONSTRAINT ck_budget_budget_side
        CHECK (side IN ('income', 'expense'))
    """,
    """
    ALTER TABLE budget_plan_line
        DROP CONSTRAINT IF EXISTS ck_budget_plan_line_budget_plan_line_side
    """,
    "ALTER TABLE budget_plan_line DROP COLUMN IF EXISTS side",
)


def upgrade() -> None:
    """Move the side to the plan lines and turn the switch-made plans into drafts."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Restore ``budget.side`` from the plan lines. The drafts stay drafts."""
    for statement in _DOWNGRADE:
        op.execute(statement)
