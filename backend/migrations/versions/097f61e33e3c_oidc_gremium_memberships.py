"""oidc_gremium_memberships: memberships and roles come from OIDC groups only.

The revision makes the IdP groups the only source of access. It links an OIDC group
in three separate ways:

- ``group_mapping``: group → global role. The revision drops its ``gremium_id``. A
  global role has no gremium scope any more.
- ``gremium_membership_mapping`` (new): group → membership in one gremium.
- ``gremium_role_mapping`` (new): group → role in a gremium. The role applies only to
  a member of that gremium.

The login sync derives every ``gremium_membership`` row from the two new tables, so
an admin can no longer set a membership by hand.

The revision also deletes the data that an admin set by hand:

- every ``gremium_membership`` row. The next login of each member writes the rows
  again from the OIDC groups and the mappings.
- every ``role_assignment`` row that the bootstrap did not grant. The bootstrap rows
  (``admin`` from the ``BOOTSTRAP_ADMIN_*`` settings and the implicit ``member``) stay.
- every ``group_mapping`` row with a gremium scope. Recreate such a right as a
  gremium role.

Idempotent. A fresh database already gets the new tables and the ``group_mapping``
without ``gremium_id`` from the ``create_all`` baseline (0001). A migrated database gets
them through ``IF [NOT] EXISTS``.

The downgrade restores the structure only, and ``group_mapping.gremium_id`` without its
foreign key. It cannot restore the deleted rows.
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
    CREATE TABLE IF NOT EXISTS gremium_membership_mapping (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        gremium_id uuid NOT NULL REFERENCES gremium (id) ON DELETE CASCADE,
        oidc_group text NOT NULL,
        CONSTRAINT uq_gremium_membership_mapping_gremium_group
            UNIQUE (gremium_id, oidc_group)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_gremium_membership_mapping_oidc_group "
        "ON gremium_membership_mapping (oidc_group)"
    ),
    """
    CREATE TABLE IF NOT EXISTS gremium_role_mapping (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        gremium_role_id uuid NOT NULL REFERENCES gremium_role (id) ON DELETE RESTRICT,
        oidc_group text NOT NULL,
        CONSTRAINT uq_gremium_role_mapping_role_group UNIQUE (gremium_role_id, oidc_group)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_gremium_role_mapping_oidc_group "
        "ON gremium_role_mapping (oidc_group)"
    ),
    "DELETE FROM gremium_membership",
    "DELETE FROM role_assignment WHERE granted_by IS DISTINCT FROM 'bootstrap'",
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'group_mapping' AND column_name = 'gremium_id'
        ) THEN
            DELETE FROM group_mapping WHERE gremium_id IS NOT NULL;
        END IF;
    END $$
    """,
    "ALTER TABLE group_mapping DROP COLUMN IF EXISTS gremium_id",
)

# The downgrade adds ``group_mapping.gremium_id`` back without its foreign key. The
# baseline downgrade drops the tables from the current ``Base.metadata``, which does not
# know that column. A foreign key to ``gremium`` would block the drop of ``gremium``.
_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE group_mapping ADD COLUMN IF NOT EXISTS gremium_id uuid",
    "DROP TABLE IF EXISTS gremium_role_mapping",
    "DROP TABLE IF EXISTS gremium_membership_mapping",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
