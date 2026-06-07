"""role_assignment: valid_from/valid_until → timestamptz (Bugfix RBAC tz-Crash)

Revision ID: 0015_role_assignment_tz
Revises: 0014_deadline_table
Create Date: 2026-06-07 00:00:15

``RoleAssignment.valid_from``/``valid_until`` waren ohne ``timezone=True`` deklariert
und landeten daher als ``timestamp without time zone`` (naiv) in Postgres. Der
RBAC-Resolver vergleicht sie mit ``datetime.now(UTC)`` (aware) → ``TypeError: can't
compare offset-naive and offset-aware datetimes``. Das legte die gesamte
Principal-Auflösung lahm — REST (500) **und** den Meeting-WS-Handshake (Dependency
``get_ws_principal`` wirft → Handshake scheitert/403) — sobald ein eingeloggter
Nutzer ein zeit-validiertes Assignment (Vertretung/Delegation) besitzt.

Auf einem **frischen** Schema entsteht die Spalte bereits korrekt als ``timestamptz``
(``Base.metadata.create_all`` in 0002, Single-Source via ``app.models``). Diese
Revision konvertiert nur **vorhandene naive** Spalten und interpretiert die Alt-Werte
als UTC (``AT TIME ZONE 'UTC'``) — idempotent (kein Doppel-Cast bei bereits
``timestamptz``). Defensiv normalisiert zusätzlich ``rbac._assignment_valid`` jeden
naiven Wert zur Laufzeit.

Lineare Kette: ``down_revision`` = ``0014_deadline_table`` → ``alembic heads`` = EIN Head.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_role_assignment_tz"
down_revision: str | None = "0014_deadline_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("valid_from", "valid_until")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "role_assignment" not in insp.get_table_names():
        return
    cols = {c["name"]: c for c in insp.get_columns("role_assignment")}
    for name in _COLUMNS:
        col = cols.get(name)
        if col is None or getattr(col["type"], "timezone", False):
            # nicht vorhanden oder bereits timestamptz → nichts zu tun
            continue
        op.alter_column(
            "role_assignment",
            name,
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{name} AT TIME ZONE 'UTC'",
            existing_nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "role_assignment" not in insp.get_table_names():
        return
    cols = {c["name"]: c for c in insp.get_columns("role_assignment")}
    for name in _COLUMNS:
        col = cols.get(name)
        if col is None or not getattr(col["type"], "timezone", False):
            continue
        op.alter_column(
            "role_assignment",
            name,
            type_=sa.DateTime(timezone=False),
            postgresql_using=f"{name} AT TIME ZONE 'UTC'",
            existing_nullable=True,
        )
