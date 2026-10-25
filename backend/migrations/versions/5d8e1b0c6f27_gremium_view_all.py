"""Gremien tab: grant ``gremium.view_all`` to the role ``admin``.

The new tab "Gremien" (``/api/gremien/...``) shows a member the own gremien. The new
global permission ``gremium.view_all`` shows every gremium: its members, meetings,
attendance and decisions. The admin bypass grants it anyway; the row makes the role
page show it. Other roles get it only by hand.

No table changes. The statement is idempotent (``ON CONFLICT DO NOTHING``).

The downgrade removes the permission rows.

Revision ID: 5d8e1b0c6f27
Revises: a3f9c2d71e4b
Create Date: 2026-10-15 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5d8e1b0c6f27"
down_revision: str | None = "a3f9c2d71e4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.execute(
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'gremium.view_all' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    op.execute("DELETE FROM role_permission WHERE permission = 'gremium.view_all'")
