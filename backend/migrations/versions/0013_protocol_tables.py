"""protocol: protocol(+vote_ref) + protocol.write-grant (T-22)

Revision ID: 0013_protocol_tables
Revises: 0011_render_job_table
Create Date: 2026-06-07 00:00:13

**Nummerierung (Strang E/parallel):** T-19 belegt 0012 (parallel, noch nicht auf main).
T-22 nimmt daher **0013**. ``down_revision`` zeigt auf den **aktuellen main-Head** —
zum Zeitpunkt der Erstellung ``0011_render_job_table`` (T-20). Sobald T-19 (0012) auf
main ist, wird vor dem Merge auf ``origin/main`` rebased und ``down_revision`` auf
``0012`` gesetzt, damit ``alembic heads`` EIN Head bleibt (keine Verzweigung an 0011).

Auf einem **frischen** Schema entstehen ``protocol`` und ``protocol_vote_ref`` bereits
über ``Base.metadata.create_all`` in 0002 (Single-Source via ``app.models``). Für vor
T-22 migrierte Schemata legt diese Revision sie **idempotent** nach (``checkfirst``).

Zusätzlich:

* Grant ``protocol.write`` an die Rollen ``admin`` **und** ``protocol`` — die vier
  Protokoll-Endpunkte (api.md »protocol«) verlangen genau diese Permission, sie war
  aber in 0003 nicht geseedet (dort nur ``protocol.manage``), also sonst unerreichbar.
  Idempotent (INSERT … WHERE NOT EXISTS) — analog dem ``form.configure``-Grant in 0010.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.models  # noqa: F401 — befüllt Base.metadata
from app.db import Base
from app.modules.protocol.models import Protocol, ProtocolVoteRef

revision: str = "0013_protocol_tables"
down_revision: str | None = "0011_render_job_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Rollen-IDs aus 0003 (admin/protocol).
_ADMIN_ROLE_ID = "00000000-0000-0000-0000-0000000000a1"
_PROTOCOL_ROLE_ID = "00000000-0000-0000-0000-0000000000a4"
_PROTOCOL_WRITE = "protocol.write"

_TABLES = [Protocol.__table__, ProtocolVoteRef.__table__]

_role_permission = sa.table(
    "role_permission",
    sa.column("role_id", sa.Uuid),
    sa.column("permission", sa.Text),
)


def _grant(role_id: str) -> None:
    op.execute(
        sa.text(
            "INSERT INTO role_permission (role_id, permission) "
            "SELECT CAST(:rid AS uuid), :perm WHERE NOT EXISTS ("
            "  SELECT 1 FROM role_permission "
            "  WHERE role_id = CAST(:rid AS uuid) AND permission = :perm)"
        ).bindparams(rid=role_id, perm=_PROTOCOL_WRITE)
    )


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=_TABLES, checkfirst=True)
    _grant(_ADMIN_ROLE_ID)
    _grant(_PROTOCOL_ROLE_ID)


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(
        sa.delete(_role_permission).where(
            _role_permission.c.role_id.in_(
                [sa.cast(_ADMIN_ROLE_ID, sa.Uuid), sa.cast(_PROTOCOL_ROLE_ID, sa.Uuid)]
            ),
            _role_permission.c.permission == _PROTOCOL_WRITE,
        )
    )
    Base.metadata.drop_all(bind=bind, tables=_TABLES, checkfirst=True)
