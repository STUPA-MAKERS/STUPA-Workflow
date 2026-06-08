"""forced gremium roles Vorstand/Schriftführung in every gremium (#Meetings)

Revision ID: 0031_forced_gremium_roles
Revises: 0030_budget_expense
Create Date: 2026-06-09 00:00:31

Jedes Gremium hat zwei Pflichtrollen — ``vorstand`` und ``schriftfuehrung`` —,
die die Sitzungsleitung bilden (steuern die Sitzungssteuerung). Hier werden sie
für **bestehende** Gremien nachgezogen; neue Gremien bekommen sie beim Anlegen
(admin-service) bzw. lazy beim Auflisten (GremiumRoleService.ensure_forced_roles).
Idempotent via ``NOT EXISTS``. ``down_revision`` = ``0030_budget_expense``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031_forced_gremium_roles"
down_revision: str | None = "0030_budget_expense"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (key, name_i18n-JSON) — synchron mit FORCED_GREMIUM_ROLES im Service halten.
_FORCED = (
    ("vorstand", '{"de": "Vorstand", "en": "Board"}'),
    ("schriftfuehrung", '{"de": "Schriftführung", "en": "Secretary"}'),
    ("member", '{"de": "Mitglied", "en": "Member"}'),
)


def upgrade() -> None:
    for key, name_json in _FORCED:
        op.execute(
            f"""
            INSERT INTO gremium_role (id, gremium_id, key, name_i18n)
            SELECT gen_random_uuid(), g.id, '{key}', '{name_json}'::jsonb
            FROM gremium g
            WHERE NOT EXISTS (
                SELECT 1 FROM gremium_role r
                WHERE r.gremium_id = g.id AND r.key = '{key}'
            )
            """
        )


def downgrade() -> None:
    keys = ", ".join(f"'{key}'" for key, _ in _FORCED)
    op.execute(f"DELETE FROM gremium_role WHERE key IN ({keys})")
