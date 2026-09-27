"""oidc_gremium_memberships: gremium memberships and roles come from OIDC groups only.

The revision adds ``gremium_group_mapping``. One row maps an OIDC group to a role in
one gremium. The login sync derives every ``gremium_membership`` row from these
mappings, so an admin can no longer set a membership by hand.

The revision also deletes the data that an admin set by hand:

- every ``gremium_membership`` row. The next login of each member writes the rows
  again from the OIDC groups and the mappings.
- every ``role_assignment`` row that the bootstrap did not grant. Global roles now
  come from ``group_mapping`` only. The bootstrap rows (``admin`` from the
  ``BOOTSTRAP_ADMIN_*`` settings and the implicit ``member``) stay.

Idempotent. A fresh database already gets the table from the ``create_all`` baseline
(0001), because ``GremiumGroupMapping`` is part of ``app.modules.admin.models``. A
migrated database gets it through ``CREATE TABLE IF NOT EXISTS``.

The downgrade drops the table only. It cannot restore the deleted rows.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "097f61e33e3c"
down_revision: str | None = "9c2e7d41b8f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS gremium_group_mapping (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        gremium_id uuid NOT NULL REFERENCES gremium (id) ON DELETE CASCADE,
        gremium_role_id uuid NOT NULL REFERENCES gremium_role (id) ON DELETE RESTRICT,
        oidc_group text NOT NULL,
        CONSTRAINT uq_gremium_group_mapping_gremium_group UNIQUE (gremium_id, oidc_group)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_gremium_group_mapping_oidc_group "
        "ON gremium_group_mapping (oidc_group)"
    ),
    "DELETE FROM gremium_membership",
    "DELETE FROM role_assignment WHERE granted_by IS DISTINCT FROM 'bootstrap'",
)

_DOWNGRADE: tuple[str, ...] = ("DROP TABLE IF EXISTS gremium_group_mapping",)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
