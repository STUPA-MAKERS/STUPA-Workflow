"""global flow redesign: state.kind/config, transition.branch, nullable flow type (#28)

Revision ID: 0023_global_flow
Revises: 0022_gremium_vote_delegation
Create Date: 2026-06-08 00:00:23

Global-Flow-Redesign (#28, Pre-Alpha harter Cutover):
* ``state.kind`` (normal/vote/approval/decision) + ``state.config`` (JSONB).
* ``transition.branch`` (pass/fail/accept/reject) — 2 feste Ausgänge der vote/approval-States.
* ``flow_version.application_type_id`` wird **nullable** (``NULL`` = globaler Flow);
  Aktiv-Unique getrennt nach global vs. per-Typ.

Idempotent (Inspector-Checks). ``down_revision`` = ``0022_gremium_vote_delegation``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_global_flow"
down_revision: str | None = "0022_gremium_vote_delegation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cols(insp: sa.Inspector, table: str) -> set[str]:
    return {c["name"] for c in insp.get_columns(table)}


def _indexes(insp: sa.Inspector, table: str) -> set[str]:
    return {i["name"] for i in insp.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "state" in tables:
        cols = _cols(insp, "state")
        if "kind" not in cols:
            op.add_column(
                "state",
                sa.Column("kind", sa.Text(), nullable=False, server_default="normal"),
            )
            op.create_check_constraint(
                "state_kind",
                "state",
                "kind IN ('normal','vote','approval','decision')",
            )
        if "config" not in cols:
            op.add_column(
                "state",
                sa.Column(
                    "config",
                    postgresql.JSONB(),
                    nullable=False,
                    server_default="{}",
                ),
            )

    if "transition" in tables and "branch" not in _cols(insp, "transition"):
        op.add_column("transition", sa.Column("branch", sa.Text(), nullable=True))

    if "flow_version" in tables:
        # application_type_id nullable (globaler Flow = NULL).
        op.alter_column("flow_version", "application_type_id", nullable=True)
        # Aktiv-Unique neu aufsetzen (global vs. per-Typ). Drop-if-exists → idempotent,
        # auch wenn das frische Schema (create_all) die Indizes schon angelegt hat.
        idx = _indexes(insp, "flow_version")
        for name in (
            "uq_flow_version_one_active_global",
            "uq_flow_version_one_active_per_type",
        ):
            if name in idx:
                op.drop_index(name, table_name="flow_version")
        op.create_index(
            "uq_flow_version_one_active_global",
            "flow_version",
            ["active"],
            unique=True,
            postgresql_where=sa.text("active AND application_type_id IS NULL"),
        )
        op.create_index(
            "uq_flow_version_one_active_per_type",
            "flow_version",
            ["application_type_id"],
            unique=True,
            postgresql_where=sa.text("active AND application_type_id IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "flow_version" in tables:
        idx = _indexes(insp, "flow_version")
        if "uq_flow_version_one_active_global" in idx:
            op.drop_index("uq_flow_version_one_active_global", table_name="flow_version")
    if "transition" in tables and "branch" in _cols(insp, "transition"):
        op.drop_column("transition", "branch")
    if "state" in tables:
        cols = _cols(insp, "state")
        if "config" in cols:
            op.drop_column("state", "config")
        if "kind" in cols:
            op.drop_constraint("state_kind", "state", type_="check")
            op.drop_column("state", "kind")
