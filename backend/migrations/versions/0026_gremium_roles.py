"""gremium_role + gremium_membership (#42 — Gremium-eigener Rollensatz, Amtszeiten)

Revision ID: 0026_gremium_roles
Revises: 0025_principal_active
Create Date: 2026-06-08 00:00:26

Gremium-Rollen sind ein **eigener** Rollensatz, getrennt von den globalen Rollen.
``gremium_membership`` hält die zeitlich begrenzte Zugehörigkeit (Amtszeit); pro
(Principal, Gremium) ist genau eine Rolle aktiv (Überlappung Service-seitig geprüft).
Idempotent (Inspector-Checks). ``down_revision`` = ``0025_principal_active``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0026_gremium_roles"
down_revision: str | None = "0025_principal_active"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "gremium_role" not in tables:
        op.create_table(
            "gremium_role",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("key", sa.Text(), nullable=False, unique=True),
            sa.Column("name_i18n", JSONB(), server_default="{}", nullable=False),
        )

    if "gremium_membership" not in tables:
        op.create_table(
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
        op.create_index(
            "ix_gremium_membership_principal", "gremium_membership", ["principal_id"]
        )
        op.create_index(
            "ix_gremium_membership_gremium", "gremium_membership", ["gremium_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "gremium_membership" in tables:
        op.drop_table("gremium_membership")
    if "gremium_role" in tables:
        op.drop_table("gremium_role")
