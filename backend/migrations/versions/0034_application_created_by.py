"""application.created_by — eingeloggte:r Ersteller:in (#24)

Revision ID: 0034_application_created_by
Revises: 0033_meeting_agenda
Create Date: 2026-06-09 00:00:34

OIDC-``sub`` der/des erstellenden Principals; erlaubt Lesen/Bearbeiten/Löschen des
eigenen Antrags ohne ``application.manage``. ``NULL`` bei anonymer Einreichung.
Reine, idempotente Spaltenergänzung.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_application_created_by"
down_revision: str | None = "0033_meeting_agenda"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("application")}
    if "created_by" not in cols:
        op.add_column("application", sa.Column("created_by", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("application")}
    if "created_by" in cols:
        op.drop_column("application", "created_by")
