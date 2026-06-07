"""role_assignment.delegated_by + Index (T-45 Vertretung/Delegation)

Revision ID: 0016_role_assignment_deleg
Revises: 0015_role_assignment_tz
Create Date: 2026-06-07 00:00:16

Selbst-Delegation/Vertretung (R1.5): ein Mitglied gibt eines seiner eigenen Rechte
zeitlich begrenzt an ein anderes ab. ``delegated_by`` trägt die ``sub`` des
delegierenden Mitglieds (bei reinen Admin-Zuweisungen aus T-24 ``NULL``) und ist der
Anker für »eigene Delegationen auflisten/widerrufen« sowie für die Doppel-Stimmrechts-
Sperre (wer sein Stimmrecht delegiert hat, darf nicht zusätzlich selbst abstimmen).

Idempotent: auf einem **frischen** Schema hat ``Base.metadata.create_all`` (0002)
Spalte + Index bereits angelegt (Single-Source via ``app.models``); diese Revision
prüft per Inspector und legt nur Fehlendes nach (für vor-T-45 migrierte Schemata).

Lineare Kette: ``down_revision`` = ``0015_role_assignment_tz`` → ``alembic heads`` =
EIN Head. (Koordination mit paralleler Rollen-Admin-Welle: kollidiert eine zweite
0016, wird beim Merge auf den dann aktuellen Head rebased.)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_role_assignment_deleg"
down_revision: str | None = "0015_role_assignment_tz"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "role_assignment"
_COLUMN = "delegated_by"
_INDEX = "ix_role_assignment_delegated_by"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns(_TABLE)}
    if _COLUMN not in columns:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))

    indexes = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
    if _INDEX not in indexes:
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return

    indexes = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name=_TABLE)

    columns = {col["name"] for col in inspector.get_columns(_TABLE)}
    if _COLUMN in columns:
        op.drop_column(_TABLE, _COLUMN)
