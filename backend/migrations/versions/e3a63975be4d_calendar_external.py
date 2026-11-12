"""calendar_external: the external calendars and their entries.

``calendar_external`` is an ICS feed that an admin subscribed, ``calendar_external_entry``
one dated entry of its newest good fetch.

Idempotent. A fresh database already gets the tables from the ``create_all`` baseline
(0001), because the models sit in ``app.models``. A migrated database gets them through
``CREATE TABLE IF NOT EXISTS``.

The revision also grants ``admin.calendars`` to the ``admin`` role, so the role table
shows it like every other permission.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e3a63975be4d"
down_revision: str | None = "5b112a444f34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS calendar_external (
        id uuid DEFAULT gen_random_uuid() NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        name text NOT NULL,
        url text NOT NULL,
        gremium_id uuid,
        interval_minutes integer NOT NULL DEFAULT 60,
        due_at timestamptz NOT NULL DEFAULT now(),
        last_attempt_at timestamptz,
        last_success_at timestamptz,
        last_error text,
        CONSTRAINT pk_calendar_external PRIMARY KEY (id),
        CONSTRAINT ck_calendar_external_interval
            CHECK (interval_minutes IN (15, 60, 360, 1440)),
        CONSTRAINT fk_calendar_external_gremium_id_gremium
            FOREIGN KEY (gremium_id) REFERENCES gremium (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_calendar_external_gremium_id ON calendar_external (gremium_id)",
    "CREATE INDEX IF NOT EXISTS ix_calendar_external_due_at ON calendar_external (due_at)",
    """
    CREATE TABLE IF NOT EXISTS calendar_external_entry (
        id uuid DEFAULT gen_random_uuid() NOT NULL,
        calendar_id uuid NOT NULL,
        title text NOT NULL,
        starts_on date NOT NULL,
        ends_on date NOT NULL,
        start_time time,
        end_time time,
        place text,
        description text,
        CONSTRAINT pk_calendar_external_entry PRIMARY KEY (id),
        CONSTRAINT ck_calendar_external_entry_days CHECK (ends_on >= starts_on),
        CONSTRAINT fk_calendar_external_entry_calendar_id_calendar_external
            FOREIGN KEY (calendar_id) REFERENCES calendar_external (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_calendar_external_entry_calendar_id "
    "ON calendar_external_entry (calendar_id)",
    "CREATE INDEX IF NOT EXISTS ix_calendar_external_entry_starts_on "
    "ON calendar_external_entry (starts_on)",
    "CREATE INDEX IF NOT EXISTS ix_calendar_external_entry_ends_on "
    "ON calendar_external_entry (ends_on)",
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'admin.calendars' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'admin.calendars'",
    "DROP TABLE IF EXISTS calendar_external_entry",
    "DROP TABLE IF EXISTS calendar_external",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
