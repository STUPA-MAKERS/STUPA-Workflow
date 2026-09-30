"""Drop the global meeting permissions; protocol.finalize becomes a gremium permission.

The meeting domain is scoped per gremium. The gremium permissions `session.manage`,
`protocol.write`, `vote.manage` and, from this revision on, `protocol.finalize` grant
it. The global keys that overlapped with them go:

- `meeting.manage`: the gremium permission `session.manage` replaces it.
- `protocol.finalize`: it becomes a gremium permission (decision O7). Finalizing
  needs the write access AND the gremium key (decision O2).
- `application.create`: no code checked it (bug F11). The public form creates an
  application without a permission.

The upgrade:

1. adds `protocol.finalize` to the forced gremium roles `vorstand` and `manager` of
   every gremium (O7). A custom gremium role does not get it.
2. logs a warning with the global roles that held one of the keys, and with the
   number of principals who lose a meeting right. That is a non-admin principal who
   held the right through a global role and has no gremium role with
   `session.manage`. Since the OIDC-only memberships, such a principal gets the
   right back only through an IdP group that maps to a gremium role.
3. deletes the `role_permission` rows of the three keys.

The downgrade is LOSSY. It restores the seed grants of revisions 0002 and 0017 for
the seeded roles that still exist (`admin`: all three keys; `manager`:
`application.create`, `meeting.manage`, `protocol.finalize`; `protocol`:
`meeting.manage`, `protocol.finalize`). A custom global role does not get its keys
back. It then removes `protocol.finalize` from every gremium role.

Both directions are idempotent.

Revision ID: 3a0b9672fcba
Revises: 14ed7a68a641
Create Date: 2026-09-30 13:58:23.560198
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3a0b9672fcba"
down_revision: str | None = "14ed7a68a641"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_DROPPED: tuple[str, ...] = ("meeting.manage", "protocol.finalize", "application.create")
_DROPPED_SQL = ", ".join(f"'{p}'" for p in _DROPPED)

# The seed grants of 0002 and 0017 per seeded global role, for the downgrade.
_SEED_GRANTS: dict[str, tuple[str, ...]] = {
    "admin": ("application.create", "meeting.manage", "protocol.finalize"),
    "manager": ("application.create", "meeting.manage", "protocol.finalize"),
    "protocol": ("meeting.manage", "protocol.finalize"),
}

_GRANT_FINALIZE = (
    "UPDATE gremium_role "
    "SET permissions = COALESCE(permissions, '[]'::jsonb) || '[\"protocol.finalize\"]'::jsonb "
    "WHERE key IN ('vorstand', 'manager') "
    "AND NOT COALESCE(permissions, '[]'::jsonb) ? 'protocol.finalize'"
)

_ROLES_WITH_DROPPED = (
    "SELECT r.key, string_agg(rp.permission, ', ' ORDER BY rp.permission) "
    "FROM role_permission rp JOIN role r ON r.id = rp.role_id "
    f"WHERE rp.permission IN ({_DROPPED_SQL}) "
    "GROUP BY r.key ORDER BY r.key"
)


# A principal holds a global role through an active role_assignment or through an
# OIDC group that a group_mapping links to the role. See `rbac.resolve_principal`.
# `role_cond` filters the `role_permission` row `rp` of that role.
def _holds_role(role_cond: str) -> str:
    return f"""
    (EXISTS (
        SELECT 1 FROM role_assignment ra
        JOIN role_permission rp ON rp.role_id = ra.role_id
        WHERE ra.principal_id = p.id AND {role_cond}
          AND (ra.valid_from IS NULL OR ra.valid_from <= now())
          AND (ra.valid_until IS NULL OR ra.valid_until > now())
    )
    OR EXISTS (
        SELECT 1 FROM group_mapping gm
        JOIN role_permission rp ON rp.role_id = gm.role_id
        WHERE {role_cond}
          AND COALESCE(p.oidc_groups, '[]'::jsonb) ? gm.oidc_group
    ))
    """


_AFFECTED_PRINCIPALS = f"""
    SELECT count(*) FROM principal p
    WHERE {_holds_role("rp.permission IN ('meeting.manage', 'protocol.finalize')")}
      AND NOT {_holds_role("rp.role_id IN (SELECT id FROM role WHERE key = 'admin')")}
      AND NOT EXISTS (
        SELECT 1 FROM gremium_membership gm
        JOIN gremium_role gr ON gr.id = gm.gremium_role_id
        WHERE gm.principal_id = p.id
          AND COALESCE(gr.permissions, '[]'::jsonb) ? 'session.manage'
          AND (gm.valid_from IS NULL OR gm.valid_from <= now())
          AND (gm.valid_until IS NULL OR gm.valid_until > now())
      )
"""


def _report() -> None:
    """Log the global roles and the principals that lose a dropped key."""
    bind = op.get_bind()
    roles = bind.execute(sa.text(_ROLES_WITH_DROPPED)).all()
    for key, perms in roles:
        logger.warning("global role %r loses the permission(s): %s", key, perms)
    affected = bind.execute(sa.text(_AFFECTED_PRINCIPALS)).scalar_one()
    if affected:
        logger.warning(
            "%d non-admin principal(s) held meeting.manage or protocol.finalize through a "
            "global role and have no gremium role with session.manage. Map their IdP "
            "groups to a gremium role to give the meeting rights back.",
            affected,
        )


def upgrade() -> None:
    op.execute(_GRANT_FINALIZE)
    _report()
    op.execute(f"DELETE FROM role_permission WHERE permission IN ({_DROPPED_SQL})")


def downgrade() -> None:
    for role_key, perms in _SEED_GRANTS.items():
        for perm in perms:
            op.execute(
                "INSERT INTO role_permission (role_id, permission) "
                f"SELECT r.id, '{perm}' FROM role r WHERE r.key = '{role_key}' "
                "ON CONFLICT DO NOTHING"
            )
    op.execute(
        "UPDATE gremium_role "
        "SET permissions = permissions - 'protocol.finalize' "
        "WHERE permissions ? 'protocol.finalize'"
    )
