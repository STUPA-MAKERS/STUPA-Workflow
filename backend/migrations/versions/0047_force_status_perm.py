"""Permission `application.force_status` (#force-status).

This global permission forces an application directly into any flow state. It bypasses
the flow guards and transitions.

The migration seeds the permission to the `admin` role, which holds all permissions. An
admin already gets the permission through the role-key bypass. The row follows the house
convention and makes the grant explicit for non-admin roles.

The insert is idempotent through `ON CONFLICT DO NOTHING`.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0047_force_status_perm"
down_revision: str | None = "0046_fints_dedup_rerun"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'application.force_status' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'application.force_status'",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
