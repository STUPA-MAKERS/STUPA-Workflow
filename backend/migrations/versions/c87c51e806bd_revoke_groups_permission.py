"""Revoke rights: grant ``admin.users.revoke_groups`` to the role ``admin``.

The new action "Rechte entziehen" on the users page (``POST
/admin/principals/{id}/revoke``) clears whole Gremien and global roles of a person who
no longer logs in. It has its own permission. The admin bypass grants it anyway; the
row makes the role page show it. Other roles get it only by hand.

No table changes. The statement is idempotent (``ON CONFLICT DO NOTHING``).

The downgrade removes the permission rows.

Revision ID: c87c51e806bd
Revises: bf0309071fb4
Create Date: 2026-10-09 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c87c51e806bd"
down_revision: str | None = "bf0309071fb4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'admin.users.revoke_groups' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM role_permission WHERE permission = 'admin.users.revoke_groups'")
