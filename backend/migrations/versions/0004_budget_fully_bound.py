"""Budget: a fully-bound flag per cost center.

Idempotent through `IF NOT EXISTS`. A fresh database already gets the column from
`create_all` (baseline), so this migration is a no-op there. A migrated database gets
the column here.

`budget.fully_bound` marks the whole allocation of the cost center, the subtree
included, as bound for each fiscal year. Then committed equals allocated and the
available amount is 0.
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
