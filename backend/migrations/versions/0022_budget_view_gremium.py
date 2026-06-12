"""Budget: ``view_gremium_id`` (#budget-scope).

Sichtbarkeits-Gremium je Kostenstelle: Mitglieder des zugeordneten Gremiums
sehen diese Kostenstelle (+ Unterbaum) im Budget-Tab als Root — ohne globale
``budget.*``-Permission. Unabhängig vom Top-Level-``gremium_id``
(Klassifikation). Idempotent (``IF NOT EXISTS``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022_budget_view_gremium"
down_revision: str | None = "0021_meeting_delete_finalized"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE budget ADD COLUMN IF NOT EXISTS "
        "view_gremium_id uuid REFERENCES gremium(id) ON DELETE SET NULL"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_budget_view_gremium_id "
        "ON budget (view_gremium_id)"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_budget_view_gremium_id",
    "ALTER TABLE budget DROP COLUMN IF EXISTS view_gremium_id",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
