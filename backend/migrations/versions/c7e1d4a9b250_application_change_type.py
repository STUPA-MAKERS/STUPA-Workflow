"""Change of the Antragsart: version columns and the permission (specs 001660, 001662).

The upgrade:

1. adds three nullable columns to ``submission_version``: ``from_type_id`` and
   ``to_type_id`` (the old and the new Antragsart of a type change) and
   ``from_form_version_id`` (the form version of the old type, for the labels of the
   fields that the new form does not have). Each column is NULL for every other
   version.
2. grants the new global permission ``application.change_type`` to the roles
   ``admin``, ``finanzreferent`` and ``haushaltsbeauftragte``. A role that does not
   exist gets nothing, because the insert selects only the existing rows.

All steps are idempotent. A fresh database gets the columns from the ``create_all``
baseline (0001), because the model already declares them, so the upgrade uses
``ADD COLUMN IF NOT EXISTS``. The insert uses ``ON CONFLICT DO NOTHING``.

The downgrade removes the role rows of the permission and drops the three columns.

Revision ID: c7e1d4a9b250
Revises: c4d1e2f3a5b6
Create Date: 2026-11-19 23:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c7e1d4a9b250"
down_revision: str | None = "c4d1e2f3a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE submission_version ADD COLUMN IF NOT EXISTS from_type_id UUID "
        "REFERENCES application_type(id) ON DELETE SET NULL"
    ),
    (
        "ALTER TABLE submission_version ADD COLUMN IF NOT EXISTS to_type_id UUID "
        "REFERENCES application_type(id) ON DELETE SET NULL"
    ),
    (
        "ALTER TABLE submission_version ADD COLUMN IF NOT EXISTS from_form_version_id UUID "
        "REFERENCES form_version(id) ON DELETE SET NULL"
    ),
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'application.change_type' FROM role r "
        "WHERE r.key IN ('admin', 'finanzreferent', 'haushaltsbeauftragte') "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'application.change_type'",
    "ALTER TABLE submission_version DROP COLUMN IF EXISTS from_form_version_id",
    "ALTER TABLE submission_version DROP COLUMN IF EXISTS to_type_id",
    "ALTER TABLE submission_version DROP COLUMN IF EXISTS from_type_id",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
