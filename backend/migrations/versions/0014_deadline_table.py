"""deadline: Fristen + Cron-Scan-Indizes (T-44)

Revision ID: 0014_deadline_table
Revises: 0013_protocol_tables
Create Date: 2026-06-07 00:00:14

**Nummerierung (Strang F/parallel):** Die Kette stand bei 0013 (T-22 Protokoll); T-44
nimmt die nächste freie Nummer 0014, ``down_revision`` = ``0013_protocol_tables``
→ lineare Kette, ``alembic heads`` = EIN Head (keine Verzweigung).

Auf einem **frischen** Schema entsteht ``deadline`` bereits über
``Base.metadata.create_all`` in 0002 (Single-Source via ``app.models``). Für vor T-44
migrierte Schemata legt diese Revision die Tabelle **idempotent** (``checkfirst``) nach —
inklusive der beiden partiellen Scan-Indizes (Auto-Fristen / Erinnerungen, flows §9.4).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import app.models  # noqa: F401 — befüllt Base.metadata
from app.db import Base
from app.modules.deadlines.models import Deadline

revision: str = "0014_deadline_table"
down_revision: str | None = "0013_protocol_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [Deadline.__table__]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=_TABLES, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=_TABLES, checkfirst=True)
