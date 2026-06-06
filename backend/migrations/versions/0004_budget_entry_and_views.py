"""budget: rollup-MVs + budget.view-permission (T-17)

Revision ID: 0004_budget_entry_and_views
Revises: 0003_seed_roles
Create Date: 2026-06-06 00:00:04

``budget_entry`` selbst entsteht – wie alle Modul-Tabellen – über
``Base.metadata.create_all`` in 0002 (Single-Source-Pattern, s. ``app.models``).
Diese Revision ergänzt, was ``create_all`` nicht abbildet:

* MVs ``mv_budget_usage`` (Topf × Stufe, Summen) + ``mv_status_distribution``
  (Gremium × State, Zähler), data-model §3 — je mit Unique-Index für
  ``REFRESH … CONCURRENTLY`` (Worker). NULL-Schlüssel via ``NULLS NOT DISTINCT``
  (Postgres 16).
* Permission ``budget.view`` (Statistik-Lesen) → admin/manager/finance.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_budget_entry_and_views"
down_revision: str | None = "0003_seed_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Rollen-UUIDs (fix, s. 0003_seed_roles) → idempotente Permission-Zuordnung.
_ROLE_IDS = {
    "admin": "00000000-0000-0000-0000-0000000000a1",
    "manager": "00000000-0000-0000-0000-0000000000a3",
    "finance": "00000000-0000-0000-0000-0000000000a5",
}
_VIEW_PERMISSION = "budget.view"

_role_permission = sa.table(
    "role_permission",
    sa.column("role_id", sa.Uuid),
    sa.column("permission", sa.Text),
)

_MV_USAGE = """
CREATE MATERIALIZED VIEW mv_budget_usage AS
SELECT be.budget_pot_id AS budget_pot_id,
       bp.period        AS period,
       be.stage         AS stage,
       COALESCE(SUM(be.amount), 0) AS total_amount,
       COUNT(*)         AS entry_count
FROM budget_entry be
JOIN budget_pot bp ON bp.id = be.budget_pot_id
GROUP BY be.budget_pot_id, bp.period, be.stage
WITH DATA
"""

_MV_STATUS = """
CREATE MATERIALIZED VIEW mv_status_distribution AS
SELECT a.gremium_id       AS gremium_id,
       a.current_state_id AS current_state_id,
       COUNT(*)           AS application_count
FROM application a
GROUP BY a.gremium_id, a.current_state_id
WITH DATA
"""


def upgrade() -> None:
    op.execute(_MV_USAGE)
    # Unique-Index (CONCURRENTLY-Voraussetzung); (pot, stage) ist eindeutig je Zeile.
    op.execute(
        "CREATE UNIQUE INDEX uq_mv_budget_usage "
        "ON mv_budget_usage (budget_pot_id, stage)"
    )

    op.execute(_MV_STATUS)
    op.execute(
        "CREATE UNIQUE INDEX uq_mv_status_distribution "
        "ON mv_status_distribution (gremium_id, current_state_id) NULLS NOT DISTINCT"
    )

    op.bulk_insert(
        _role_permission,
        [
            {"role_id": _ROLE_IDS[key], "permission": _VIEW_PERMISSION}
            for key in _ROLE_IDS
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.delete(_role_permission).where(
            _role_permission.c.permission == _VIEW_PERMISSION
        )
    )
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_status_distribution")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_budget_usage")
