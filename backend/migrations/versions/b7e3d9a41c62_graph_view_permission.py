"""Graph: the global permission ``graph.view``.

The upgrade grants ``graph.view`` to the role ``admin`` (spec 001421). The admin bypass
grants it anyway; the row makes the role page show it. No other seeded role gets it.

Idempotent. The downgrade removes the permission rows of every role.

Revision ID: b7e3d9a41c62
Revises: c4d1e2f3a5b6
Create Date: 2026-11-19 21:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b7e3d9a41c62"
down_revision: str | None = "c4d1e2f3a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Grant the permission to the admin role."""
    op.execute(
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'graph.view' FROM role r WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    """Remove the permission from every role."""
    op.execute("DELETE FROM role_permission WHERE permission = 'graph.view'")
