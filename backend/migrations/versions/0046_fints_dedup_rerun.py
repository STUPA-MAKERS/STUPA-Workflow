"""fints_dedup_rerun: start the deduplication cleanup again (#fints-dedup).

An earlier version of 0045 already ran on the database. ``alembic_version`` marks it as
applied, so alembic does NOT run it again, even after a code fix. This **new** revision
therefore calls the corrected raw-data cleanup ``bank.maintenance.dedup_staged_lines`` on
the existing data. The logic is the same as in 0045 and stays idempotent. The revision
duplicates no script. It only calls the same function again.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0046_fints_dedup_rerun"
down_revision: str | None = "0045_fints_dedup_staged"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.modules.budget.bank.maintenance import dedup_staged_lines

    dedup_staged_lines(op.get_bind())


def downgrade() -> None:
    pass
