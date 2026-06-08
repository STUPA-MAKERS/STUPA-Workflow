"""form_version.description_i18n (#13 — NC-Forms-Beschreibung)

Revision ID: 0028_form_version_description
Revises: 0027_gremium_role_per_gremium
Create Date: 2026-06-08 00:00:28

Eine Form-Version trägt jetzt eine optionale, mehrsprachige Markdown-Beschreibung
(NC-Forms-Stil: Titel = ``application_type.name_i18n``, Beschreibung hier). Reine
Spaltenergänzung, idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0028_form_version_description"
down_revision: str | None = "0027_gremium_role_per_gremium"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("form_version")}
    if "description_i18n" not in cols:
        op.add_column(
            "form_version",
            sa.Column("description_i18n", JSONB(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("form_version")}
    if "description_i18n" in cols:
        op.drop_column("form_version", "description_i18n")
