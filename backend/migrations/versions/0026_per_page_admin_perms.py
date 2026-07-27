"""Per-page admin permissions (#per-page-admin): remap the existing assignments.

The person and access management that `admin.roles` gated before now gets one
permission per admin page. `admin.deadlines` splits the deadline page out of
`admin.types`.

* `admin.roles` keeps /admin/roles. Its holders also get `admin.users`,
  `admin.group_mappings`, `admin.gremium_roles` and `admin.delegations`. The
  reach of the permission stays exactly the same.
* `admin.types` stays for application types, forms and flows. Its holders also
  get `admin.deadlines`, because the deadline page sat under `admin.types`.

All statements are idempotent (`ON CONFLICT DO NOTHING`). `admin.roles` and
`admin.types` stay in place. This migration deletes no permission.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026_per_page_admin_perms"
down_revision: str | None = "0025_invoices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fanout(old: str, new: tuple[str, ...]) -> list[str]:
    """Build the INSERTs that add the `new` permissions to every holder of `old`.

    The statements only add permissions. They never remove `old`.

    Returns:
        One SQL statement per entry in `new`.
    """
    return [
        (
            "INSERT INTO role_permission (role_id, permission) "
            f"SELECT role_id, '{n}' FROM role_permission "
            f"WHERE permission = '{old}' "
            "ON CONFLICT DO NOTHING"
        )
        for n in new
    ]


_NEW_FROM_ROLES = (
    "admin.users",
    "admin.group_mappings",
    "admin.gremium_roles",
    "admin.delegations",
)

_UPGRADE: tuple[str, ...] = (
    *_fanout("admin.roles", _NEW_FROM_ROLES),
    *_fanout("admin.types", ("admin.deadlines",)),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission IN "
    "('admin.users', 'admin.group_mappings', 'admin.gremium_roles', "
    "'admin.delegations', 'admin.deadlines')",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
