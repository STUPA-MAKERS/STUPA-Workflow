"""CD logos: the slot ``square`` for the 1:1 logo of a Gremium.

The upgrade widens the check constraint ``ck_cd_variant_logo_slot`` to
``title``, ``footer`` and ``square``. It adds the partial unique index
``uq_cd_variant_logo_square``, so a variant holds at most one square logo.

The statements are idempotent. A fresh database already gets the wide check and
the index from the ``create_all`` baseline (0001), because the model declares
them.

The downgrade deletes the square rows first, because the narrow check refuses
them. Their objects stay in the bucket as orphans, which is harmless. It then
drops the index and restores the narrow check.

Revision ID: a3f9c2d71e4b
Revises: 4e1b7a93c2d5
Create Date: 2026-10-15 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a3f9c2d71e4b"
down_revision: str | None = "4e1b7a93c2d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.execute("ALTER TABLE cd_variant_logo DROP CONSTRAINT IF EXISTS ck_cd_variant_logo_slot")
    op.execute(
        "ALTER TABLE cd_variant_logo ADD CONSTRAINT ck_cd_variant_logo_slot "
        "CHECK (slot IN ('title', 'footer', 'square'))"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cd_variant_logo_square "
        "ON cd_variant_logo (variant_id) WHERE slot = 'square'"
    )


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    op.execute("DELETE FROM cd_variant_logo WHERE slot = 'square'")
    op.execute("DROP INDEX IF EXISTS uq_cd_variant_logo_square")
    op.execute("ALTER TABLE cd_variant_logo DROP CONSTRAINT IF EXISTS ck_cd_variant_logo_slot")
    op.execute(
        "ALTER TABLE cd_variant_logo ADD CONSTRAINT ck_cd_variant_logo_slot "
        "CHECK (slot IN ('title', 'footer'))"
    )
