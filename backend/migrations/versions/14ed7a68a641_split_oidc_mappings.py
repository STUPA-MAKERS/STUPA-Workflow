"""split_oidc_mappings: link OIDC groups to global roles, gremien and gremium roles separately.

Revision ``097f61e33e3c`` mapped an OIDC group to a gremium and a gremium role in one
row (``gremium_group_mapping``). Global roles could still carry a gremium scope. These
three things are not related, so this revision gives each its own link:

- ``group_mapping``: group → global role. The revision deletes the rows with a gremium
  scope and drops ``gremium_id``. Recreate such a right as a gremium role.
- ``gremium_membership_mapping`` (new): group → membership in one gremium.
- ``gremium_role_mapping`` (new): group → role in a gremium, for members only.

The revision converts every ``gremium_group_mapping`` row: the group becomes a member of
the gremium, and gets the role through a role mapping unless the role is the forced
``member``, which every member has anyway. Then it drops ``gremium_group_mapping``. The
login sync keeps the derived memberships unchanged by this conversion.

Idempotent. A fresh database gets the new tables and ``group_mapping`` without
``gremium_id`` from the ``create_all`` baseline (0001). ``097f61e33e3c`` then creates
``gremium_group_mapping`` again, empty, and this revision drops it.

The downgrade restores the structure only: ``gremium_group_mapping`` empty, and
``group_mapping.gremium_id`` without its foreign key. The baseline downgrade drops the
tables from the current ``Base.metadata``, which does not know that column, so a
foreign key to ``gremium`` would block the drop of ``gremium``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "14ed7a68a641"
down_revision: str | None = "097f61e33e3c"
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
    """
    DO $$
    BEGIN
        IF to_regclass('gremium_group_mapping') IS NOT NULL THEN
            INSERT INTO gremium_membership_mapping (gremium_id, oidc_group)
                SELECT DISTINCT gremium_id, oidc_group FROM gremium_group_mapping
                ON CONFLICT DO NOTHING;
            INSERT INTO gremium_role_mapping (gremium_role_id, oidc_group)
                SELECT m.gremium_role_id, m.oidc_group
                FROM gremium_group_mapping m
                JOIN gremium_role r ON r.id = m.gremium_role_id
                WHERE r.key <> 'member'
                ON CONFLICT DO NOTHING;
        END IF;
    END $$
    """,
    "DROP TABLE IF EXISTS gremium_group_mapping",
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

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE group_mapping ADD COLUMN IF NOT EXISTS gremium_id uuid",
    """
    CREATE TABLE IF NOT EXISTS gremium_group_mapping (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        gremium_id uuid NOT NULL REFERENCES gremium (id) ON DELETE CASCADE,
        gremium_role_id uuid NOT NULL REFERENCES gremium_role (id) ON DELETE RESTRICT,
        oidc_group text NOT NULL,
        CONSTRAINT uq_gremium_group_mapping_gremium_group UNIQUE (gremium_id, oidc_group)
    )
    """,
    "DROP TABLE IF EXISTS gremium_role_mapping",
    "DROP TABLE IF EXISTS gremium_membership_mapping",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
