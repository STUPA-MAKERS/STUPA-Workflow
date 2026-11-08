"""Ticket kind ``barrier``: a report of an accessibility barrier (spec 000497).

The upgrade replaces the check ``ck_ticket_kind`` with one that also accepts
``barrier``. The key is named like the baseline names it, so both paths match. A
fresh database already gets the new check from the ``create_all`` baseline (0001),
because the models sit in ``app.models``.

The downgrade turns every barrier ticket into a ``bug`` (the old check refuses
``barrier``) and restores the old check.

Revision ID: db31a12f701e
Revises: 9f1cd0d72646
Create Date: 2026-11-08 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "db31a12f701e"
down_revision: str | None = "9f1cd0d72646"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_ticket_kind"

_UPGRADE: tuple[str, ...] = (
    f"ALTER TABLE ticket DROP CONSTRAINT IF EXISTS {_CHECK}",
    (
        f"ALTER TABLE ticket ADD CONSTRAINT {_CHECK} "
        "CHECK (kind IN ('bug', 'question', 'idea', 'barrier'))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "UPDATE ticket SET kind = 'bug' WHERE kind = 'barrier'",
    f"ALTER TABLE ticket DROP CONSTRAINT IF EXISTS {_CHECK}",
    f"ALTER TABLE ticket ADD CONSTRAINT {_CHECK} CHECK (kind IN ('bug', 'question', 'idea'))",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
