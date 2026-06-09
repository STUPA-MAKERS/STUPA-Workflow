"""flow state: add color, drop category (#state-color)

Revision ID: 0046_state_color
Revises: 0045_drop_notification_rules
Create Date: 2026-06-09 18:00:00

Flow-States bekommen eine konfigurierbare Anzeigefarbe (``color``) für ihr
Tag/Badge. Das bisherige ``category``-Feld (open/running/closed) ist damit
überflüssig und wird samt Check-Constraint ``state_category`` entfernt.
Idempotent (Inspector-Check). ``down_revision`` = ``0045_drop_notification_rules``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046_state_color"
down_revision: str | None = "0045_drop_notification_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("state")}
    if "color" not in cols:
        op.add_column("state", sa.Column("color", sa.Text(), nullable=True))

    constraints = {c["name"] for c in insp.get_check_constraints("state")}
    if "state_category" in constraints:
        op.drop_constraint("state_category", "state", type_="check")
    if "category" in cols:
        op.drop_column("state", "category")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("state")}
    if "category" not in cols:
        op.add_column(
            "state",
            sa.Column(
                "category", sa.Text(), nullable=False, server_default="open"
            ),
        )
    constraints = {c["name"] for c in insp.get_check_constraints("state")}
    if "state_category" not in constraints:
        op.create_check_constraint(
            "state_category",
            "state",
            "category IN ('open','running','closed')",
        )
    if "color" in cols:
        op.drop_column("state", "color")
