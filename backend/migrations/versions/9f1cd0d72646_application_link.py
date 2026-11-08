"""application_link: the Vorgänger of an application and the history of its changes.

``application_link`` holds at most one Vorgänger per application (the primary key is
the application). ``application_link_event`` records each set and each removal for the
history of the application.

Idempotent. A fresh database already gets both tables from the ``create_all`` baseline
(0001), because both models sit in ``app.models``. A migrated database gets them through
``CREATE TABLE IF NOT EXISTS``.

Revision ID: 9f1cd0d72646
Revises: 08dfb2c28b9a
Create Date: 2026-11-08 09:40:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "9f1cd0d72646"
down_revision: str | None = "08dfb2c28b9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS application_link (
        application_id uuid NOT NULL,
        predecessor_id uuid NOT NULL,
        linked_by text,
        linked_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_application_link PRIMARY KEY (application_id),
        CONSTRAINT fk_application_link_application_id_application
            FOREIGN KEY (application_id) REFERENCES application (id) ON DELETE CASCADE,
        CONSTRAINT fk_application_link_predecessor_id_application
            FOREIGN KEY (predecessor_id) REFERENCES application (id) ON DELETE CASCADE,
        CONSTRAINT ck_application_link_not_self CHECK (application_id <> predecessor_id)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_application_link_predecessor_id "
        "ON application_link (predecessor_id)"
    ),
    """
    CREATE TABLE IF NOT EXISTS application_link_event (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        application_id uuid NOT NULL,
        predecessor_id uuid,
        action text NOT NULL,
        actor text,
        at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT fk_application_link_event_application_id_application
            FOREIGN KEY (application_id) REFERENCES application (id) ON DELETE CASCADE,
        CONSTRAINT fk_application_link_event_predecessor_id_application
            FOREIGN KEY (predecessor_id) REFERENCES application (id) ON DELETE SET NULL,
        CONSTRAINT ck_application_link_event_action CHECK (action IN ('set','removed'))
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_application_link_event_application_id_at "
        "ON application_link_event (application_id, at)"
    ),
)


def upgrade() -> None:
    """Create ``application_link`` and ``application_link_event``."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop both tables."""
    op.execute("DROP TABLE IF EXISTS application_link_event")
    op.execute("DROP TABLE IF EXISTS application_link")
