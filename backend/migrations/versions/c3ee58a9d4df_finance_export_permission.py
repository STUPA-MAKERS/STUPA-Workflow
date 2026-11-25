"""Permissions: the export key of the finance pages is ``finance.export``.

The upgrade renames ``budget.export`` to ``finance.export`` in every role
(F/finance/budget/003016), because the key also gives the export of the Bestellungen.
Each role that had the old key has the new one, and no other role gets it. The step is
idempotent: the insert skips a role that has the new key, and the delete finds nothing
on a second run.

Revision ID: c3ee58a9d4df
Revises: 7b3d9e5a2c18
Create Date: 2026-11-25 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c3ee58a9d4df"
down_revision: str | None = "7b3d9e5a2c18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename(old: str, new: str) -> tuple[str, str]:
    """Build the statements that give ``new`` to each holder of ``old`` and drop ``old``."""
    return (
        "INSERT INTO role_permission (role_id, permission) "
        f"SELECT role_id, '{new}' FROM role_permission WHERE permission = '{old}' "
        "ON CONFLICT DO NOTHING",
        f"DELETE FROM role_permission WHERE permission = '{old}'",
    )


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _rename("budget.export", "finance.export"):
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    for stmt in _rename("finance.export", "budget.export"):
        op.execute(stmt)
