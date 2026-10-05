"""Applications captured on behalf of an applicant (#11).

The upgrade:

1. adds three nullable columns to `application`: `captured_by` (the OIDC `sub` of the
   capturing person, no foreign key), `capture_intake` (the free-text intake channel)
   and `received_on` (the date on which the application reached the Gremium). The
   columns stay NULL for an application that the applicant submitted.
2. grants the new global permission `application.create_on_behalf` to the `admin`
   role. An admin already holds it through the role-key bypass. The row makes the
   grant explicit, as for the other permissions.

All steps are idempotent. A fresh database gets the columns from the `create_all`
baseline (0001), because the model already declares them, so the upgrade uses
`ADD COLUMN IF NOT EXISTS`. The insert uses `ON CONFLICT DO NOTHING`.

The downgrade removes the role rows of the permission and drops the three columns.

Revision ID: b6a6464a36b9
Revises: 373c9fe9cafb
Create Date: 2026-10-05 22:37:26.961170
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b6a6464a36b9"
down_revision: str | None = "373c9fe9cafb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE application ADD COLUMN IF NOT EXISTS captured_by TEXT",
    "ALTER TABLE application ADD COLUMN IF NOT EXISTS capture_intake TEXT",
    "ALTER TABLE application ADD COLUMN IF NOT EXISTS received_on DATE",
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'application.create_on_behalf' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'application.create_on_behalf'",
    "ALTER TABLE application DROP COLUMN IF EXISTS received_on",
    "ALTER TABLE application DROP COLUMN IF EXISTS capture_intake",
    "ALTER TABLE application DROP COLUMN IF EXISTS captured_by",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
