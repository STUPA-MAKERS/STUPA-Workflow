"""calendar_appointments: the Termin tables of the Kalender.

``calendar_appointment`` is a Termin, ``calendar_invitation`` one invited Gremium or
person, ``calendar_answer`` the answer of one invited person.

Idempotent. A fresh database already gets the tables from the ``create_all`` baseline
(0001), because the models sit in ``app.models``. A migrated database gets them through
``CREATE TABLE IF NOT EXISTS``.

The revision also grants ``calendar.manage`` and ``calendar.publish`` to the ``admin``
role, so the role table shows them like every other permission.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5b112a444f34"
down_revision: str | None = "9c4f2e7a1d38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS calendar_appointment (
        id uuid DEFAULT gen_random_uuid() NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        title text NOT NULL,
        starts_on date NOT NULL,
        ends_on date NOT NULL,
        start_time time,
        end_time time,
        place text,
        description text,
        creator_id uuid,
        for_all boolean NOT NULL DEFAULT false,
        sequence integer NOT NULL DEFAULT 0,
        CONSTRAINT pk_calendar_appointment PRIMARY KEY (id),
        CONSTRAINT ck_calendar_appointment_days CHECK (ends_on >= starts_on),
        CONSTRAINT ck_calendar_appointment_times CHECK (
            (start_time IS NULL AND end_time IS NULL) OR
            (start_time IS NOT NULL AND end_time IS NOT NULL AND
             (ends_on > starts_on OR end_time > start_time))
        ),
        CONSTRAINT fk_calendar_appointment_creator_id_principal
            FOREIGN KEY (creator_id) REFERENCES principal (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_calendar_appointment_starts_on "
    "ON calendar_appointment (starts_on)",
    "CREATE INDEX IF NOT EXISTS ix_calendar_appointment_ends_on "
    "ON calendar_appointment (ends_on)",
    "CREATE INDEX IF NOT EXISTS ix_calendar_appointment_creator_id "
    "ON calendar_appointment (creator_id)",
    """
    CREATE TABLE IF NOT EXISTS calendar_invitation (
        id uuid DEFAULT gen_random_uuid() NOT NULL,
        appointment_id uuid NOT NULL,
        gremium_id uuid,
        principal_id uuid,
        CONSTRAINT pk_calendar_invitation PRIMARY KEY (id),
        CONSTRAINT ck_calendar_invitation_target
            CHECK ((gremium_id IS NULL) <> (principal_id IS NULL)),
        CONSTRAINT fk_calendar_invitation_appointment_id_calendar_appointment
            FOREIGN KEY (appointment_id) REFERENCES calendar_appointment (id) ON DELETE CASCADE,
        CONSTRAINT fk_calendar_invitation_gremium_id_gremium
            FOREIGN KEY (gremium_id) REFERENCES gremium (id) ON DELETE CASCADE,
        CONSTRAINT fk_calendar_invitation_principal_id_principal
            FOREIGN KEY (principal_id) REFERENCES principal (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_calendar_invitation_gremium_id "
    "ON calendar_invitation (gremium_id)",
    "CREATE INDEX IF NOT EXISTS ix_calendar_invitation_principal_id "
    "ON calendar_invitation (principal_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_calendar_invitation_principal "
    "ON calendar_invitation (appointment_id, principal_id) WHERE principal_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_calendar_invitation_gremium "
    "ON calendar_invitation (appointment_id, gremium_id) WHERE gremium_id IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS calendar_answer (
        appointment_id uuid NOT NULL,
        principal_id uuid NOT NULL,
        answer text NOT NULL,
        answered_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_calendar_answer PRIMARY KEY (appointment_id, principal_id),
        CONSTRAINT ck_calendar_answer_answer
            CHECK (answer IN ('accept','tentative','decline')),
        CONSTRAINT fk_calendar_answer_appointment_id_calendar_appointment
            FOREIGN KEY (appointment_id) REFERENCES calendar_appointment (id) ON DELETE CASCADE,
        CONSTRAINT fk_calendar_answer_principal_id_principal
            FOREIGN KEY (principal_id) REFERENCES principal (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_calendar_answer_principal_id "
    "ON calendar_answer (principal_id)",
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, p.permission FROM role r "
        "CROSS JOIN (VALUES ('calendar.manage'), ('calendar.publish')) AS p(permission) "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission IN ('calendar.manage', 'calendar.publish')",
    "DROP TABLE IF EXISTS calendar_answer",
    "DROP TABLE IF EXISTS calendar_invitation",
    "DROP TABLE IF EXISTS calendar_appointment",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
