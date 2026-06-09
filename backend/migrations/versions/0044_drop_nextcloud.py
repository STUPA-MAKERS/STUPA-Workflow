"""Drop Nextcloud-WebDAV export columns (render_job/protocol.nextcloud_path)

Revision ID: 0044_drop_nextcloud
Revises: 0043_export_permissions
Create Date: 2026-06-09 16:00:00

Der Nextcloud-WebDAV-Export-Pfad wurde vollständig aus dem Backend entfernt (PDFs
liegen ausschließlich in MinIO). Die beiden Spiegel-Spalten ``render_job.nextcloud_path``
und ``protocol.nextcloud_path`` werden daher gedroppt. Idempotent über den Inspector
(Spalte nur droppen, wenn Tabelle + Spalte existieren). ``downgrade`` legt die Spalten
als nullable ``Text`` wieder an.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_drop_nextcloud"
down_revision: str | None = "0043_export_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("render_job", "protocol")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    table_names = set(insp.get_table_names())
    for table in _TABLES:
        if table not in table_names:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if "nextcloud_path" in cols:
            op.drop_column(table, "nextcloud_path")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    table_names = set(insp.get_table_names())
    for table in _TABLES:
        if table not in table_names:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if "nextcloud_path" not in cols:
            op.add_column(
                table, sa.Column("nextcloud_path", sa.Text(), nullable=True)
            )
