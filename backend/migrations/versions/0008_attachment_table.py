"""files: attachment (T-13)

Revision ID: 0008_attachment_table
Revises: 0007_voting_tables
Create Date: 2026-06-06 00:00:08

Wie alle Modul-Tabellen entsteht ``attachment`` auf einem **frischen** Schema bereits
über ``Base.metadata.create_all`` in 0002 (Single-Source via ``app.models``). Für bereits
vor T-13 migrierte Schemata legt diese Revision sie **idempotent** nach: ``create_all(...,
checkfirst=True)`` erzeugt nur fehlende Tabellen, überspringt sie auf frischen DBs.

CHECK(size <= 10485760) + FK ``application_id`` ON DELETE CASCADE kommen aus dem Modell
(data-model §1, security.md §6).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import app.models  # noqa: F401  — befüllt Base.metadata
from app.db import Base
from app.modules.files.models import Attachment

revision: str = "0008_attachment_table"
down_revision: str | None = "0007_voting_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [Attachment.__table__]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=_TABLES, checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=_TABLES, checkfirst=True)
