"""Permission `application.delete` (#g9).

Seeds the new permission to the `admin` role. The insert is idempotent.

Revision ID: ad9651a045a8
Revises: ec167d091656
Create Date: 2026-08-06 15:37:57.682054
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "ad9651a045a8"
down_revision: str | None = "ec167d091656"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'application.delete' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'application.delete'",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
