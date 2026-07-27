"""Transition: an optional color (#flow).

The color paints the arrow in the flow editor and the decision button on the
application. It replaces the color heuristic that read a word list. NULL means no
color, so the default rendering applies. Idempotent through `IF [NOT] EXISTS`.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009_transition_color"
down_revision: str | None = "0008_oauth_token_lifetime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE transition ADD COLUMN IF NOT EXISTS color text",
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE transition DROP COLUMN IF EXISTS color",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
