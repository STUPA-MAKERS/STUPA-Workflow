"""Haushaltsplan: a line can name its Vorgänger in the year before (spec 001040).

``budget_plan_line`` gets ``predecessor_id``, the cost center of the line in the plan
in force of the year before that the line compares with. The delete of that cost
center sets it to NULL, so the line then compares with its own cost center again.

Idempotent. A fresh database already has the column from the ``create_all`` baseline
(0001), because the model sits in ``app.models``.

Revision ID: 5e7a2c9d4b18
Revises: 9a69ebacd008
Create Date: 2026-11-16 02:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5e7a2c9d4b18"
down_revision: str | None = "9a69ebacd008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE budget_plan_line ADD COLUMN IF NOT EXISTS predecessor_id uuid",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid = 'budget_plan_line'::regclass
               AND conname = 'fk_budget_plan_line_predecessor_id_budget'
        ) THEN
            ALTER TABLE budget_plan_line ADD CONSTRAINT fk_budget_plan_line_predecessor_id_budget
                FOREIGN KEY (predecessor_id) REFERENCES budget (id) ON DELETE SET NULL;
        END IF;
    END $$
    """,
)


def upgrade() -> None:
    """Add the Vorgänger of a plan line."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the Vorgänger of a plan line."""
    op.execute(
        "ALTER TABLE budget_plan_line DROP CONSTRAINT IF EXISTS "
        "fk_budget_plan_line_predecessor_id_budget"
    )
    op.execute("ALTER TABLE budget_plan_line DROP COLUMN IF EXISTS predecessor_id")
