"""gremium.allow_vote_delegation (#14 — Stimm-Delegation pro Gremium)

Revision ID: 0022_gremium_vote_delegation
Revises: 0021_transition_automatic
Create Date: 2026-06-08 00:00:22

Stimm-Delegation ist eine Eigenschaft des **Gremiums**, nicht der einzelnen
Rollenzuweisung. Default ``false``. Idempotent (Spalte per Inspector geprüft).

Lineare Kette: ``down_revision`` = ``0021_transition_automatic``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_gremium_vote_delegation"
down_revision: str | None = "0021_transition_automatic"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "gremium"
_COLUMN = "allow_vote_delegation"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns(_TABLE)}
    if _COLUMN not in columns:
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN, sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns(_TABLE)}
    if _COLUMN in columns:
        op.drop_column(_TABLE, _COLUMN)
