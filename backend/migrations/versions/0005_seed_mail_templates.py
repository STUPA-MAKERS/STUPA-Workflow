"""notifications: seed default-mail-templates (T-18)

Revision ID: 0005_seed_mail_templates
Revises: 0004_budget_entry_and_views
Create Date: 2026-06-06 00:00:05

Die Tabellen ``notification_rule``/``mail_template`` entstehen — wie alle
Modul-Tabellen — über ``Base.metadata.create_all`` in 0002 (Single-Source-Pattern,
s. ``app.models``). Diese Revision seedet nur minimale Default-Templates (DE/EN):

* ``magic_link``    — Zugangslink für Antragsteller (ersetzt T-10-Platzhalter).
* ``status_update`` — Statuswechsel-Benachrichtigung (data-model §5.4 Beispiel).

Feste UUIDs → idempotenter Insert + sauberer Downgrade. Bodies sind Jinja2
(``{{ link }}`` / ``{{ status }}`` …); konkrete Texte sind via Admin-API änderbar.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005_seed_mail_templates"
down_revision: str | None = "0004_budget_entry_and_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MAGIC_LINK_ID = "00000000-0000-0000-0000-0000000000e1"
_STATUS_UPDATE_ID = "00000000-0000-0000-0000-0000000000e2"

_mail_template = sa.table(
    "mail_template",
    sa.column("id", sa.Uuid),
    sa.column("key", sa.Text),
    sa.column("subject_i18n", JSONB),
    sa.column("body_i18n", JSONB),
    sa.column("body_html_i18n", JSONB),
    sa.column("placeholders", JSONB),
)

_TEMPLATES = [
    {
        "id": _MAGIC_LINK_ID,
        "key": "magic_link",
        "subject_i18n": {
            "de": "Ihr Zugangslink zur Antragsplattform",
            "en": "Your access link for the application platform",
        },
        "body_i18n": {
            "de": (
                "Hallo,\n\nüber diesen Link gelangen Sie zu Ihrem Antrag:\n{{ link }}\n\n"
                "Der Link ist zeitlich begrenzt gültig. Wenn Sie das nicht angefordert "
                "haben, ignorieren Sie diese Mail.\n"
            ),
            "en": (
                "Hello,\n\nuse this link to access your application:\n{{ link }}\n\n"
                "The link is valid for a limited time. If you did not request it, "
                "ignore this email.\n"
            ),
        },
        "body_html_i18n": {},
        "placeholders": {"link": "Magic-Link-URL"},
    },
    {
        "id": _STATUS_UPDATE_ID,
        "key": "status_update",
        "subject_i18n": {
            "de": "Statusänderung Ihres Antrags",
            "en": "Your application status changed",
        },
        "body_i18n": {
            "de": (
                "Hallo,\n\nder Status Ihres Antrags hat sich geändert: {{ status }}.\n"
            ),
            "en": ("Hello,\n\nyour application status has changed: {{ status }}.\n"),
        },
        "body_html_i18n": {},
        "placeholders": {"status": "Neuer Status (Label)"},
    },
]


def upgrade() -> None:
    op.bulk_insert(_mail_template, _TEMPLATES)


def downgrade() -> None:
    op.execute(
        sa.delete(_mail_template).where(
            _mail_template.c.id.in_([_MAGIC_LINK_ID, _STATUS_UPDATE_ID])
        )
    )
