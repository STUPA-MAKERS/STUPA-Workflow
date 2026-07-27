"""drop_fully_bound: remove the fully-bound cost center feature.

The migration drops the column ``budget.fully_bound`` that 0004 added. A cost center
again counts only its real applications and expenses. The synthetic full bind is gone.
The migration is idempotent (``IF EXISTS``). The down round trip restores the column as
NOT NULL DEFAULT false.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0036_drop_fully_bound"
down_revision: str | None = "0035_fints_bank_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE budget DROP COLUMN IF EXISTS fully_bound")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE budget ADD COLUMN IF NOT EXISTS "
        "fully_bound boolean NOT NULL DEFAULT false"
    )
