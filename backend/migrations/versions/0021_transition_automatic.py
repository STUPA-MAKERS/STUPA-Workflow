"""transition.automatic (#8 — automatische Übergänge)

Revision ID: 0021_transition_automatic
Revises: 0020_budget_hierarchy
Create Date: 2026-06-08 00:00:21

Markiert einen Übergang als **automatisch**: er feuert ohne Nutzer-Aktion, sobald
sein Guard erfüllt ist (Worker wertet das zyklisch aus, ``flow.fire(manual=False)``).
Default ``false`` → bestehende Übergänge bleiben manuell.

Idempotent: auf einem frischen Schema legt ``Base.metadata.create_all`` die Spalte
bereits an (Single-Source via ``app.models``); diese Revision prüft per Inspector und
legt nur Fehlendes nach.

Lineare Kette: ``down_revision`` = ``0020_budget_hierarchy`` → ``alembic heads`` = EIN Head.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_transition_automatic"
down_revision: str | None = "0020_budget_hierarchy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "transition"
_COLUMN = "automatic"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns(_TABLE)}
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
    columns = {col["name"] for col in inspector.get_columns(_TABLE)}
    if _COLUMN in columns:
        op.drop_column(_TABLE, _COLUMN)
