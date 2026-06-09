"""budget: color + accepted/denied state keys (#budget-redesign)

Revision ID: 0041_budget_color_states
Revises: 0040_sessions_rework
Create Date: 2026-06-09 16:00:00

Kostenstellen bekommen eine optionale Anzeigefarbe (``color``) sowie — nur am
Top-Level genutzt — ``accepted_state_keys``/``denied_state_keys`` (Flow-State-Keys,
die als angenommen bzw. abgelehnt gelten; alles andere = beantragt). Idempotent
(Inspector-Check). ``down_revision`` = ``0040_sessions_rework``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0041_budget_color_states"
down_revision: str | None = "0040_sessions_rework"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("budget")}
    if "color" not in cols:
        op.add_column("budget", sa.Column("color", sa.Text(), nullable=True))
    if "accepted_state_keys" not in cols:
        op.add_column(
            "budget",
            sa.Column(
                "accepted_state_keys",
                JSONB(),
                server_default="[]",
                nullable=False,
            ),
        )
    if "denied_state_keys" not in cols:
        op.add_column(
            "budget",
            sa.Column(
                "denied_state_keys",
                JSONB(),
                server_default="[]",
                nullable=False,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("budget")}
    for name in ("denied_state_keys", "accepted_state_keys", "color"):
        if name in cols:
            op.drop_column("budget", name)
