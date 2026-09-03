"""backup_catalogue: the ``backup`` table plus the ``backup.manage`` permission.

The table is the catalogue of whole-platform archives that ``/admin/backups`` lists.
It holds metadata only. Every archive lives in the backup bucket in MinIO,
age-encrypted, under ``storage_key``.

Idempotent. A fresh database already gets the table from the ``create_all`` baseline
(0001), because ``Backup`` sits in ``app.models``. A migrated database gets it through
``CREATE TABLE IF NOT EXISTS``.

``created_by`` holds the OIDC ``sub``, not a ``principal`` id. A restore replaces the
principal table along with everything else, and a catalogue row has to survive an actor
that the restored state no longer knows.

The revision also grants ``backup.manage`` to the ``admin`` role. The permission is
separate from every ``admin.*`` page permission, because its holder can read the whole
database and replace it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f3b3f1a022b5"
down_revision: str | None = "ad9651a045a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS backup (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        kind text NOT NULL DEFAULT 'manual',
        status text NOT NULL DEFAULT 'pending',
        created_by text,
        storage_key text,
        size_bytes bigint,
        checksum text,
        object_count integer,
        note text,
        app_version text,
        schema_revision text,
        pinned boolean NOT NULL DEFAULT false,
        error text,
        finished_at timestamptz,
        CONSTRAINT ck_backup_backup_status
            CHECK (status IN ('pending','running','done','failed')),
        CONSTRAINT ck_backup_backup_kind
            CHECK (kind IN ('manual','scheduled','pre_restore','imported'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_backup_created_at ON backup (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_backup_status ON backup (status)",
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'backup.manage' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'backup.manage'",
    "DROP TABLE IF EXISTS backup",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
