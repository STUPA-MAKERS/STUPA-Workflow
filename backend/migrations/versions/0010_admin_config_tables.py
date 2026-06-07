"""admin: webhook(+delivery) + site_config_version + form.configure-grant (T-24)

Revision ID: 0010_admin_config_tables
Revises: 0009_meeting_and_vote_fk
Create Date: 2026-06-07 00:00:10

Auf einem **frischen** Schema entstehen ``webhook``, ``webhook_delivery`` und
``site_config_version`` bereits über ``Base.metadata.create_all`` in 0002 (Single
Source via ``app.models``). Für vor T-24 migrierte Schemata legt diese Revision die
Tabellen **idempotent** nach (``checkfirst``).

Zusätzlich:

* Grant ``form.configure`` an die ``admin``-Rolle — die Berechtigung wird von den
  Bestands-Endpunkten ``form-versions`` (T-11) verlangt, war aber in 0003 nicht
  geseedet (sonst unerreichbar). Idempotent (INSERT … WHERE NOT EXISTS).
* Seed einer initialen **aktiven** ``site_config_version`` (v1, leeres Branding),
  damit ``GET /api/site-config`` immer eine aktive Version liefert (#21).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

import app.models  # noqa: F401 — befüllt Base.metadata
from app.db import Base
from app.modules.admin.models import SiteConfigVersion, Webhook, WebhookDelivery

revision: str = "0010_admin_config_tables"
down_revision: str | None = "0009_meeting_and_vote_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADMIN_ROLE_ID = "00000000-0000-0000-0000-0000000000a1"
_FORM_CONFIGURE = "form.configure"
_SITE_CONFIG_SEED_ID = "00000000-0000-0000-0000-0000000000c1"

_NEW_TABLES = [
    Webhook.__table__,
    WebhookDelivery.__table__,
    SiteConfigVersion.__table__,
]

_role_permission = sa.table(
    "role_permission",
    sa.column("role_id", sa.Uuid),
    sa.column("permission", sa.Text),
)
_site_config = sa.table(
    "site_config_version",
    sa.column("id", sa.Uuid),
    sa.column("version", sa.Integer),
    sa.column("active", sa.Boolean),
    sa.column("branding", JSONB),
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=_NEW_TABLES, checkfirst=True)

    # form.configure → admin (idempotent, sonst sind die T-11-form-version-Endpunkte
    # für niemanden erreichbar).
    op.execute(
        sa.text(
            "INSERT INTO role_permission (role_id, permission) "
            "SELECT CAST(:rid AS uuid), :perm WHERE NOT EXISTS ("
            "  SELECT 1 FROM role_permission "
            "  WHERE role_id = CAST(:rid AS uuid) AND permission = :perm)"
        ).bindparams(rid=_ADMIN_ROLE_ID, perm=_FORM_CONFIGURE)
    )

    # Initiale aktive Site-Config (leeres Branding) — idempotent über festen Key.
    op.execute(
        sa.text(
            "INSERT INTO site_config_version (id, version, active, branding) "
            "SELECT CAST(:id AS uuid), 1, true, '{}'::jsonb WHERE NOT EXISTS ("
            "  SELECT 1 FROM site_config_version)"
        ).bindparams(id=_SITE_CONFIG_SEED_ID)
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(
        sa.delete(_role_permission).where(
            _role_permission.c.role_id == _ADMIN_ROLE_ID,
            _role_permission.c.permission == _FORM_CONFIGURE,
        )
    )
    Base.metadata.drop_all(bind=bind, tables=_NEW_TABLES, checkfirst=True)
