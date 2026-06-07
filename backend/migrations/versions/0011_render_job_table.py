"""pdf: render_job (T-20)

Revision ID: 0011_render_job_table
Revises: 0010_admin_config_tables
Create Date: 2026-06-07 00:00:11

Wie alle Modul-Tabellen entsteht ``render_job`` auf einem **frischen** Schema bereits
über ``Base.metadata.create_all`` in 0002 (Single-Source via ``app.models``). Für bereits
vor T-20 migrierte Schemata legt diese Revision sie **idempotent** nach: ``create_all(...,
checkfirst=True)`` erzeugt nur fehlende Tabellen, überspringt sie auf frischen DBs.

CHECK(status IN …) + FK ``application_id`` ON DELETE CASCADE + UNIQUE(idempotency_key)
kommen aus dem Modell (api.md »pdf«, flows §6).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import app.models  # noqa: F401  — befüllt Base.metadata
from app.db import Base
from app.modules.pdf.models import RenderJob

revision: str = "0011_render_job_table"
down_revision: str | None = "0010_admin_config_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [RenderJob.__table__]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=_TABLES, checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=_TABLES, checkfirst=True)
