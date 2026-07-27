"""Budget: `hidden_in_budget` (#budget-hide).

The flag changes the display only. The budget tab hides a marked cost center and
its whole subtree. Rollups, the available-amount calculation and the export stay
unchanged. The migration is idempotent (`IF NOT EXISTS`).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020_budget_hidden_in_budget"
down_revision: str | None = "0019_drop_type_flows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE budget ADD COLUMN IF NOT EXISTS "
        "hidden_in_budget boolean NOT NULL DEFAULT false"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE budget DROP COLUMN IF EXISTS hidden_in_budget",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
