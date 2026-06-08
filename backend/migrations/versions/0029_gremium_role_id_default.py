"""gremium_role/_membership.id DEFAULT gen_random_uuid() (Fix #62)

Revision ID: 0029_gremium_role_id_default
Revises: 0028_form_version_description
Create Date: 2026-06-08 00:00:29

0026/0027 erzeugten ``gremium_role`` und ``gremium_membership`` per Hand-
``create_table`` **ohne** Server-Default auf ``id`` — anders als die Kern-
Tabellen (via ``Base.metadata.create_all``, das den ``UUIDPkMixin``-Default
``gen_random_uuid()`` übernimmt). Das ORM überlässt die ID-Erzeugung der DB
(INSERT ohne ``id``), also schlug jedes INSERT mit ``NotNullViolation`` fehl.
Hier den Default nachziehen. Idempotent. ``down_revision`` = ``0028``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029_gremium_role_id_default"
down_revision: str | None = "0028_form_version_description"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("gremium_role", "gremium_membership")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id DROP DEFAULT")
