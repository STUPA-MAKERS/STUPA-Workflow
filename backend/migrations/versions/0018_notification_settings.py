"""Plattform-Benachrichtigungs-Config + Aufgaben-Erinnerungen (#task-reminder).

* ``notification_settings`` — Single-Row (id=1): Schwelle/Wiederholung der
  Aufgaben-Erinnerungen, admin-gepflegt über ``/admin/notification-settings``.
* ``task_reminder_log`` — letzter Erinnerungs-Versand je Antrag (gebunden an
  den State-Aufenthalt via ``status_event``).
* Neue Permission ``admin.notifications``: an alle Rollen verteilt, die
  ``admin.site`` halten (Bereichs-Logik wie Migration 0016).

Idempotent (``IF NOT EXISTS`` / ``ON CONFLICT DO NOTHING``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_notification_settings"
down_revision: str | None = "0017_granular_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    (
        "CREATE TABLE IF NOT EXISTS notification_settings ("
        "id integer PRIMARY KEY DEFAULT 1, "
        "task_reminder_enabled boolean NOT NULL DEFAULT true, "
        "task_reminder_after_days integer NOT NULL DEFAULT 5, "
        "task_reminder_repeat_days integer NOT NULL DEFAULT 7, "
        "CONSTRAINT notification_settings_singleton CHECK (id = 1), "
        "CONSTRAINT task_reminder_after_days_min "
        "CHECK (task_reminder_after_days >= 1), "
        "CONSTRAINT task_reminder_repeat_days_min "
        "CHECK (task_reminder_repeat_days >= 0))"
    ),
    "INSERT INTO notification_settings (id) VALUES (1) ON CONFLICT DO NOTHING",
    (
        "CREATE TABLE IF NOT EXISTS task_reminder_log ("
        "application_id uuid PRIMARY KEY "
        "REFERENCES application(id) ON DELETE CASCADE, "
        "status_event_id uuid REFERENCES status_event(id) ON DELETE SET NULL, "
        "reminded_at timestamptz NOT NULL)"
    ),
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT role_id, 'admin.notifications' FROM role_permission "
        "WHERE permission = 'admin.site' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP TABLE IF EXISTS task_reminder_log",
    "DROP TABLE IF EXISTS notification_settings",
    "DELETE FROM role_permission WHERE permission = 'admin.notifications'",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
