"""application_archive: ``archived_at``/``archived_by`` plus ``application.archive``.

Archiving moves an application out of the working list. It is NOT a flow state: an
application can be archived from any state, and the flow records where a decision stands,
not whether the record is still in front of anyone. It is also NOT anonymization —
``be-privacy`` erases PII under the DSGVO, while archiving hides nothing and deletes
nothing.

A timestamp rather than a boolean, because it answers "whether" and "when" in one column
and makes the un-archive obvious.

``archived_by`` holds the OIDC ``sub`` and is deliberately not a foreign key, the same way
``created_by`` is not: a principal can be removed, and the record of who archived has to
survive that.

Idempotent. A fresh database already has the columns from the ``create_all`` baseline
(0001), because ``Application`` sits in ``app.models``; a migrated database gets them
through ``ADD COLUMN IF NOT EXISTS``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c4a91e77b2d0"
down_revision: str | None = "f3b3f1a022b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE application ADD COLUMN IF NOT EXISTS archived_at timestamptz",
    "ALTER TABLE application ADD COLUMN IF NOT EXISTS archived_by text",
    # Every listing query filters on this column, because the default list hides the
    # archived rows.
    (
        "CREATE INDEX IF NOT EXISTS ix_application_archived_at "
        "ON application (archived_at)"
    ),
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'application.archive' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'application.archive'",
    "DROP INDEX IF EXISTS ix_application_archived_at",
    "ALTER TABLE application DROP COLUMN IF EXISTS archived_by",
    "ALTER TABLE application DROP COLUMN IF EXISTS archived_at",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
