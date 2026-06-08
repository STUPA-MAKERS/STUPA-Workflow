"""gremium_role pro Gremium (#62) — gremium_id-FK + Unique(gremium_id, key)

Revision ID: 0027_gremium_role_per_gremium
Revises: 0026_gremium_roles
Create Date: 2026-06-08 00:00:27

Gremium-Rollen sind nun **pro Gremium** statt global. Pre-Alpha + frische Tabellen
(0026): die beiden Tabellen werden idempotent neu erzeugt, wenn ``gremium_role``
noch keine ``gremium_id``-Spalte hat. ``down_revision`` = ``0026_gremium_roles``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0027_gremium_role_per_gremium"
down_revision: str | None = "0026_gremium_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_membership(op_) -> None:  # noqa: ANN001
    op_.create_table(
        "gremium_membership",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "principal_id",
            sa.Uuid(),
            sa.ForeignKey("principal.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "gremium_id",
            sa.Uuid(),
            sa.ForeignKey("gremium.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "gremium_role_id",
            sa.Uuid(),
            sa.ForeignKey("gremium_role.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
    )
    op_.create_index("ix_gremium_membership_principal", "gremium_membership", ["principal_id"])
    op_.create_index("ix_gremium_membership_gremium", "gremium_membership", ["gremium_id"])


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    has_gremium_id = "gremium_role" in tables and "gremium_id" in {
        c["name"] for c in insp.get_columns("gremium_role")
    }
    if has_gremium_id:
        return  # bereits migriert

    if "gremium_membership" in tables:
        op.drop_table("gremium_membership")
    if "gremium_role" in tables:
        op.drop_table("gremium_role")

    op.create_table(
        "gremium_role",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "gremium_id",
            sa.Uuid(),
            sa.ForeignKey("gremium.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name_i18n", JSONB(), server_default="{}", nullable=False),
        sa.UniqueConstraint("gremium_id", "key", name="uq_gremium_role_gremium_key"),
    )
    _create_membership(op)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "gremium_membership" in tables:
        op.drop_table("gremium_membership")
    if "gremium_role" in tables:
        op.drop_table("gremium_role")
    # Vor-Zustand (0026: global) wiederherstellen.
    op.create_table(
        "gremium_role",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("name_i18n", JSONB(), server_default="{}", nullable=False),
    )
    _create_membership(op)
