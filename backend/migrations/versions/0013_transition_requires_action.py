"""Transition: ``requires_action`` (#requires-action, Tasks-Tab-Filter).

Markiert, ob ein feuerbarer manueller Übergang als **offene Aufgabe** des
Akteurs zählt (Default ``true`` = bisheriges Verhalten). Sind alle feuerbaren
Übergänge eines Antrags ``requires_action=false``, taucht er nicht mehr unter
»Aufgaben« auf — rein optionale Aktionen erzeugen keine Pseudo-Aufgaben.
Idempotent (``IF NOT EXISTS``).
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
