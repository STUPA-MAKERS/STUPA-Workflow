"""Drop the notification-rules engine; seed deadline_approaching template

Revision ID: 0045_drop_notification_rules
Revises: 0044_drop_nextcloud
Create Date: 2026-06-09 18:00:00

Die standalone Notifications-**Regeln** entfallen — ``notify`` ist jetzt eine
Flow-Graph-Action (ad-hoc ``templateKey`` + ``recipients``), die Frist-Erinnerung
ist ein **direkter** Notify. Daher:

1. ``DROP TABLE notification_rule`` (idempotent via Inspector).
2. ``DELETE FROM role_permission WHERE permission = 'notification.manage'``
   (das Admin-Notifications-Recht entfällt mitsamt der Admin-Seite).
3. Seed eines ``deadline_approaching``-MailTemplates (DE/EN), das der direkte
   Notify aus ``worker/deadlines.py`` rendert. Idempotent über feste UUID.

``downgrade`` legt die ``notification_rule``-Tabelle wieder an und entfernt das
geseedete Template. Die ``notification.manage``-``role_permission``-Zeilen werden
beim Downgrade **nicht** wiederhergestellt (Datenverlust akzeptiert).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0045_drop_notification_rules"
down_revision: str | None = "0044_drop_nextcloud"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEADLINE_TEMPLATE_ID = "00000000-0000-0000-0000-0000000000e3"

# Event-Whitelist für den CHECK der (im Downgrade) wiederhergestellten Tabelle.
_EVENTS: tuple[str, ...] = (
    "application_created",
    "application_updated",
    "status_changed",
    "vote_opened",
    "vote_closed",
    "application_approved",
    "application_rejected",
    "comment_added",
    "budget_reserved",
    "budget_booked",
    "protocol_finalized",
    "deadline_approaching",
    "deadline_passed",
)
_EVENT_CHECK = "event IN (" + ", ".join(f"'{e}'" for e in _EVENTS) + ")"

_mail_template = sa.table(
    "mail_template",
    sa.column("id", sa.Uuid),
    sa.column("key", sa.Text),
    sa.column("subject_i18n", JSONB),
    sa.column("body_i18n", JSONB),
    sa.column("body_html_i18n", JSONB),
    sa.column("placeholders", JSONB),
)

_DEADLINE_TEMPLATE = {
    "id": _DEADLINE_TEMPLATE_ID,
    "key": "deadline_approaching",
    "subject_i18n": {
        "de": "Erinnerung: Frist läuft bald ab",
        "en": "Reminder: deadline approaching",
    },
    "body_i18n": {
        "de": (
            "Hallo,\n\neine Frist zu Ihrem Antrag läuft bald ab "
            "(fällig am {{ dueAt }}).\n\nBitte handeln Sie rechtzeitig.\n"
        ),
        "en": (
            "Hello,\n\na deadline for your application is approaching "
            "(due on {{ dueAt }}).\n\nPlease act in time.\n"
        ),
    },
    "body_html_i18n": {},
    "placeholders": {
        "deadlineId": "Frist-ID",
        "dueAt": "Fälligkeitszeitpunkt (ISO-8601)",
    },
}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    table_names = set(insp.get_table_names())

    # 1. notification_rule droppen (idempotent).
    if "notification_rule" in table_names:
        op.drop_table("notification_rule")

    # 2. notification.manage-Rechte entfernen.
    if "role_permission" in table_names:
        op.execute(
            sa.text(
                "DELETE FROM role_permission WHERE permission = 'notification.manage'"
            )
        )

    # 3. deadline_approaching-Template seeden (idempotent über key).
    existing = bind.execute(
        sa.text("SELECT 1 FROM mail_template WHERE key = 'deadline_approaching'")
    ).first()
    if existing is None:
        op.bulk_insert(_mail_template, [_DEADLINE_TEMPLATE])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    table_names = set(insp.get_table_names())

    # Template wieder entfernen.
    op.execute(
        sa.delete(_mail_template).where(
            _mail_template.c.id == _DEADLINE_TEMPLATE_ID
        )
    )

    # notification_rule-Tabelle wiederherstellen (Spalten = altes Modell).
    if "notification_rule" not in table_names:
        op.create_table(
            "notification_rule",
            sa.Column(
                "id",
                sa.Uuid(),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "application_type_id",
                sa.Uuid(),
                sa.ForeignKey("application_type.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("event", sa.Text(), nullable=False),
            sa.Column("recipients", JSONB(), server_default="[]", nullable=False),
            sa.Column("template_key", sa.Text(), nullable=False),
            sa.Column(
                "enabled", sa.Boolean(), server_default="true", nullable=False
            ),
            sa.CheckConstraint(_EVENT_CHECK, name="notification_rule_event"),
        )
        op.create_index(
            "ix_notification_rule_event", "notification_rule", ["event"]
        )
        op.create_index(
            "ix_notification_rule_application_type_id",
            "notification_rule",
            ["application_type_id"],
        )
    # Hinweis: notification.manage-role_permission-Zeilen werden nicht restauriert.
