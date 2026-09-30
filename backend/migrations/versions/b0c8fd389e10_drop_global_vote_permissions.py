"""Drop the global vote permissions; voting rights are gremium permissions only.

The gremium permissions `vote.manage` and `vote.cast` of the gremium role catalog
supersede the global keys of the same name:

- `vote.manage`: the admin role, or the gremium permission `vote.manage` or
  `session.manage` in the gremium of the vote, manages a vote.
- `vote.cast`: only the gremium permission `vote.cast` grants a ballot. A vote names
  its gremium UUID as `eligible_group`. The API refuses a free group key (422).

The upgrade:

1. logs a warning for each vote whose `eligible_group` is not the UUID of an existing
   gremium, with its id and status, and the count. Such a vote can no longer be cast,
   and only the admin role can manage it. The upgrade does NOT delete or change it.
2. logs a warning for each application vote whose `eligible_group` is not the gremium
   of the application. The API now refuses such a new vote (422
   `eligible_group_mismatch`). The upgrade does NOT change it.
3. logs the global roles that held one of the keys, and the number of non-admin
   principals who lose a vote right: they held the key through a global role and have
   no gremium role with the same key. Since the OIDC-only memberships, such a
   principal gets the right back only through an IdP group that maps to a gremium
   role.
4. deletes the `role_permission` rows of the two keys.

The downgrade is LOSSY. It restores the seed grants of revision 0002 for the seeded
roles that still exist (`admin`: both keys; `manager`: `vote.manage`; `member`:
`vote.cast`). A custom global role does not get its keys back.

Both directions are idempotent.

Revision ID: b0c8fd389e10
Revises: 3a0b9672fcba
Create Date: 2026-09-30 17:17:11.136834
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0c8fd389e10"
down_revision: str | None = "3a0b9672fcba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_DROPPED: tuple[str, ...] = ("vote.cast", "vote.manage")
_DROPPED_SQL = ", ".join(f"'{p}'" for p in _DROPPED)

# The seed grants of 0002 per seeded global role, for the downgrade.
_SEED_GRANTS: dict[str, tuple[str, ...]] = {
    "admin": ("vote.cast", "vote.manage"),
    "manager": ("vote.manage",),
    "member": ("vote.cast",),
}

_UUID_RE = "^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$"

_FREE_KEY_VOTES = f"""
    SELECT v.id, v.status, v.eligible_group FROM vote v
    WHERE v.eligible_group !~* '{_UUID_RE}'
       OR NOT EXISTS (SELECT 1 FROM gremium g WHERE g.id::text = lower(v.eligible_group))
    ORDER BY v.id
"""

_MISMATCHED_VOTES = """
    SELECT v.id, v.status, v.application_id, v.eligible_group, a.gremium_id FROM vote v
    JOIN application a ON a.id = v.application_id
    WHERE a.gremium_id IS NOT NULL
      AND lower(v.eligible_group) <> a.gremium_id::text
    ORDER BY v.id
"""

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


def _affected_principals(perm: str) -> str:
    """Count the non-admin principals with the global `perm` and no gremium `perm`."""
    return f"""
    SELECT count(*) FROM principal p
    WHERE {_holds_role(f"rp.permission = '{perm}'")}
      AND NOT {_holds_role("rp.role_id IN (SELECT id FROM role WHERE key = 'admin')")}
      AND NOT EXISTS (
        SELECT 1 FROM gremium_membership gm
        JOIN gremium_role gr ON gr.id = gm.gremium_role_id
        WHERE gm.principal_id = p.id
          AND COALESCE(gr.permissions, '[]'::jsonb) ? '{perm}'
          AND (gm.valid_from IS NULL OR gm.valid_from <= now())
          AND (gm.valid_until IS NULL OR gm.valid_until > now())
      )
    """


def _report() -> None:
    """Log the votes, the global roles and the principals that the change affects."""
    bind = op.get_bind()
    free = bind.execute(sa.text(_FREE_KEY_VOTES)).all()
    for vote_id, status, group in free:
        logger.warning(
            "vote %s (status %s) has eligible_group %r, which is not a gremium id. "
            "Nobody can cast in it, and only the admin role can manage it.",
            vote_id,
            status,
            group,
        )
    if free:
        logger.warning("%d vote(s) have no gremium as eligible_group; kept as-is.", len(free))
    mismatched = bind.execute(sa.text(_MISMATCHED_VOTES)).all()
    for vote_id, status, app_id, group, gremium_id in mismatched:
        logger.warning(
            "vote %s (status %s) of application %s has eligible_group %s, but the "
            "application belongs to gremium %s; kept as-is.",
            vote_id,
            status,
            app_id,
            group,
            gremium_id,
        )
    roles = bind.execute(sa.text(_ROLES_WITH_DROPPED)).all()
    for key, perms in roles:
        logger.warning("global role %r loses the permission(s): %s", key, perms)
    for perm in _DROPPED:
        affected = bind.execute(sa.text(_affected_principals(perm))).scalar_one()
        if affected:
            logger.warning(
                "%d non-admin principal(s) held %s through a global role and have no "
                "gremium role with it. Map their IdP groups to a gremium role to give "
                "the right back.",
                affected,
                perm,
            )


def upgrade() -> None:
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
