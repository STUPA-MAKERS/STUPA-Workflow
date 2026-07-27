"""Transition: `requires_action` (#requires-action, filter of the tasks tab).

The flag marks whether a firable manual transition counts as an **open task** of
the actor. The default `true` keeps the earlier behavior. An application drops
out of the tasks tab when every firable transition has `requires_action=false`.
An optional action therefore creates no pseudo task. The migration is idempotent
(`IF NOT EXISTS`).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_transition_requires_action"
down_revision: str | None = "0012_vote_cancelled_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE transition ADD COLUMN IF NOT EXISTS "
        "requires_action boolean NOT NULL DEFAULT true"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE transition DROP COLUMN IF EXISTS requires_action",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
