"""Haushaltsplan: a line can set the Ansatz and the Ist of the year before by hand (spec 001042).

``budget_plan_line`` gets ``prev_amount`` and ``prev_actual``. A value replaces the
figure that the line takes from its Vorgänger, its own cost center or the rows below
it. NULL keeps the computed figure. A value is 0 or more.

Idempotent. A fresh database already has the columns from the ``create_all`` baseline
(0001), because the model sits in ``app.models``.

Revision ID: a3f1c7e2d905
Revises: c6010961aa02
Create Date: 2026-11-16 10:40:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a3f1c7e2d905"
down_revision: str | None = "c6010961aa02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, condition: str) -> str:
    return f"""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid = 'budget_plan_line'::regclass
               AND conname = '{name}'
        ) THEN
            ALTER TABLE budget_plan_line ADD CONSTRAINT {name} CHECK ({condition});
        END IF;
    END $$
    """


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE budget_plan_line ADD COLUMN IF NOT EXISTS prev_amount numeric(12, 2)",
    "ALTER TABLE budget_plan_line ADD COLUMN IF NOT EXISTS prev_actual numeric(12, 2)",
    _check("ck_budget_plan_line_budget_plan_line_prev_amount", "prev_amount >= 0"),
    _check("ck_budget_plan_line_budget_plan_line_prev_actual", "prev_actual >= 0"),
)


def upgrade() -> None:
    """Add the figures of the year before that a plan line sets by hand."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the figures of the year before that a plan line sets by hand."""
    for name in ("prev_amount", "prev_actual"):
        op.execute(
            "ALTER TABLE budget_plan_line DROP CONSTRAINT IF EXISTS "
            f"ck_budget_plan_line_budget_plan_line_{name}"
        )
        op.execute(f"ALTER TABLE budget_plan_line DROP COLUMN IF EXISTS {name}")
