"""drop the budget pot feature

Removes ``budget_entry``, ``budget_field`` and ``budget_pot``, plus
``application.budget_pot_id``.

The cost-centre tree is a different feature and is NOT touched: ``budget``,
``fiscal_year``, ``budget_allocation``, ``budget_expense`` and ``invoice`` stay, as
does ``application.budget_id``. Every table here is named in full for that reason.

Idempotent: the 0001 baseline builds from ``Base.metadata``, so on a fresh database
these tables never exist.

Revision ID: b41d7c9e05aa
Revises: a7c3f1e59d84
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b41d7c9e05aa"
down_revision: str | Sequence[str] | None = "a7c3f1e59d84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Both views read budget_entry. mv_budget_usage is pot-only; mv_budget_rollup was
    # superseded by the live roll-up in tree_rules.rollup_committed, which reads
    # accepted_state_keys. Neither is read, and nothing replaces them.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_budget_usage")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_budget_rollup")
    op.execute("ALTER TABLE application DROP COLUMN IF EXISTS budget_pot_id")
    # budget_entry first: it references budget_pot.
    op.execute("DROP TABLE IF EXISTS budget_entry")
    op.execute("DROP TABLE IF EXISTS budget_field")
    op.execute("DROP TABLE IF EXISTS budget_pot")


def downgrade() -> None:
    """Nothing to restore.

    The rows are gone, and the models are gone with them, so the 0001 baseline no
    longer knows these tables. Recreating the shells here leaves budget_entry holding
    a foreign key to `application`, which the baseline's own downgrade then cannot
    drop.
    """
