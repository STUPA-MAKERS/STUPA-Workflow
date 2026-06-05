"""core: seed default-rollen + permissions (+ dev-demo-gremium)

Revision ID: 0003_seed_roles
Revises: 0002_core_tables
Create Date: 2026-06-05 00:00:03

Default-Rollen (admin/member/manager/protocol/finance) + Permission-Zuordnung
(data-model §4). Demo-`gremium` nur im development-Profil. Feste UUIDs →
idempotent + downgrade-bar.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.settings import get_settings

revision: str = "0003_seed_roles"
down_revision: str | None = "0002_core_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_IDS = {
    "admin": "00000000-0000-0000-0000-0000000000a1",
    "member": "00000000-0000-0000-0000-0000000000a2",
    "manager": "00000000-0000-0000-0000-0000000000a3",
    "protocol": "00000000-0000-0000-0000-0000000000a4",
    "finance": "00000000-0000-0000-0000-0000000000a5",
}
DEMO_GREMIUM_ID = "00000000-0000-0000-0000-0000000000d1"

ROLE_NAMES = {
    "admin": {"de": "Administrator", "en": "Administrator"},
    "member": {"de": "Mitglied", "en": "Member"},
    "manager": {"de": "Sachbearbeitung", "en": "Manager"},
    "protocol": {"de": "Protokoll", "en": "Protocol"},
    "finance": {"de": "Finanzen", "en": "Finance"},
}

ALL_PERMISSIONS = [
    "application.read",
    "application.create",
    "application.update",
    "application.transition",
    "vote.manage",
    "vote.cast",
    "meeting.manage",
    "protocol.manage",
    "budget.manage",
    "notification.manage",
    "webhook.manage",
    "audit.read",
    "admin.config",
    "admin.roles",
]
ROLE_PERMISSIONS = {
    "admin": ALL_PERMISSIONS,
    "member": ["application.read", "vote.cast"],
    "manager": [
        "application.read",
        "application.create",
        "application.update",
        "application.transition",
        "vote.manage",
        "meeting.manage",
        "budget.manage",
    ],
    "protocol": ["application.read", "meeting.manage", "protocol.manage"],
    "finance": ["application.read", "budget.manage"],
}

_role = sa.table(
    "role",
    sa.column("id", sa.Uuid),
    sa.column("key", sa.Text),
    sa.column("name_i18n", JSONB),
)
_role_permission = sa.table(
    "role_permission",
    sa.column("role_id", sa.Uuid),
    sa.column("permission", sa.Text),
)
_gremium = sa.table(
    "gremium",
    sa.column("id", sa.Uuid),
    sa.column("name", sa.Text),
    sa.column("slug", sa.Text),
    sa.column("cd_variant", sa.Text),
    sa.column("default_lang", sa.Text),
)


def upgrade() -> None:
    op.bulk_insert(
        _role,
        [
            {"id": ROLE_IDS[key], "key": key, "name_i18n": ROLE_NAMES[key]}
            for key in ROLE_IDS
        ],
    )
    op.bulk_insert(
        _role_permission,
        [
            {"role_id": ROLE_IDS[key], "permission": perm}
            for key, perms in ROLE_PERMISSIONS.items()
            for perm in perms
        ],
    )
    if get_settings().environment == "development":
        op.bulk_insert(
            _gremium,
            [
                {
                    "id": DEMO_GREMIUM_ID,
                    "name": "Demo-Gremium",
                    "slug": "demo",
                    "cd_variant": "stupa",
                    "default_lang": "de",
                }
            ],
        )


def downgrade() -> None:
    op.execute(sa.delete(_gremium).where(_gremium.c.id == DEMO_GREMIUM_ID))
    role_ids = list(ROLE_IDS.values())
    op.execute(
        sa.delete(_role_permission).where(_role_permission.c.role_id.in_(role_ids))
    )
    op.execute(sa.delete(_role).where(_role.c.id.in_(role_ids)))
