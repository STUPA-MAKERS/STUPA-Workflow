"""Account merge: ``principal.merged_into``/``merged_at`` plus ``admin.users.merge``.

The OIDC provider moved from Keycloak to authentik. Every principal from the Keycloak
time has an old ``sub``, so one person can have two rows. An admin merges the old row
into the new one (``POST /admin/principals/{id}/merge``). The merge rewrites the
references and keeps the old row as a locked reference:

- ``merged_into`` points at the principal that the old row was merged into. The FK
  is ``ON DELETE RESTRICT``: a merge target stays.
- ``merged_at`` is the time of the merge. A CHECK binds it to ``merged_into``.
- A CHECK refuses a principal that points at itself.
- An index on ``merged_into`` serves the re-point of earlier merges.

The upgrade also grants the new permission ``admin.users.merge`` to the role
``admin``. The admin bypass grants it anyway. The row makes the role page show it.

Idempotent. A fresh database already has the columns from the ``create_all``
baseline (0001), because ``Principal`` sits in ``app.models``. A migrated database
gets them through ``ADD COLUMN IF NOT EXISTS``, and the constraints only when they
are missing.

The downgrade removes the permission rows, the constraints and the columns. It
cannot restore the rewritten references of a merge that already ran.

Revision ID: 3858ad137185
Revises: b6a6464a36b9
Create Date: 2026-10-05 23:07:49.833816
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "3858ad137185"
down_revision: str | None = "b6a6464a36b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_constraint(name: str, ddl: str) -> str:
    """Add a constraint to ``principal`` only when it is missing (idempotent)."""
    return (
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN "
        f"ALTER TABLE principal ADD CONSTRAINT {name} {ddl}; "
        "END IF; END $$"
    )


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE principal ADD COLUMN IF NOT EXISTS merged_into uuid",
    "ALTER TABLE principal ADD COLUMN IF NOT EXISTS merged_at timestamptz",
    _add_constraint(
        "fk_principal_merged_into_principal",
        "FOREIGN KEY (merged_into) REFERENCES principal (id) ON DELETE RESTRICT",
    ),
    _add_constraint(
        "ck_principal_not_self_merged", "CHECK (merged_into IS NULL OR merged_into <> id)"
    ),
    _add_constraint(
        "ck_principal_merged_at_set", "CHECK ((merged_into IS NULL) = (merged_at IS NULL))"
    ),
    "CREATE INDEX IF NOT EXISTS ix_principal_merged_into ON principal (merged_into)",
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'admin.users.merge' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'admin.users.merge'",
    "DROP INDEX IF EXISTS ix_principal_merged_into",
    "ALTER TABLE principal DROP CONSTRAINT IF EXISTS ck_principal_merged_at_set",
    "ALTER TABLE principal DROP CONSTRAINT IF EXISTS ck_principal_not_self_merged",
    "ALTER TABLE principal DROP CONSTRAINT IF EXISTS fk_principal_merged_into_principal",
    "ALTER TABLE principal DROP COLUMN IF EXISTS merged_at",
    "ALTER TABLE principal DROP COLUMN IF EXISTS merged_into",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
