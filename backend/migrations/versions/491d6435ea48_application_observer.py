"""application_observer: the e-mail addresses that observe an application.

An observer reads the application in the applicant view without the personal fields
and gets its status mails. The pair (application, e-mail) is unique, and the e-mail
index serves the access check and the lists of an address.

Idempotent. A fresh database already gets the table from the ``create_all`` baseline
(0001), because the model sits in ``app.models``. A migrated database gets it through
``CREATE TABLE IF NOT EXISTS``.

Revision ID: 491d6435ea48
Revises: d85b3e6a1f47
Create Date: 2026-11-12 09:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "491d6435ea48"
down_revision: str | None = "d85b3e6a1f47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS application_observer (
        id uuid NOT NULL DEFAULT gen_random_uuid(),
        application_id uuid NOT NULL,
        email citext NOT NULL,
        added_by text,
        added_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_application_observer PRIMARY KEY (id),
        CONSTRAINT fk_application_observer_application_id_application
            FOREIGN KEY (application_id) REFERENCES application (id) ON DELETE CASCADE,
        CONSTRAINT uq_application_observer_application_id_email
            UNIQUE (application_id, email)
    )
    """,
    ("CREATE INDEX IF NOT EXISTS ix_application_observer_email ON application_observer (email)"),
)


def upgrade() -> None:
    """Create ``application_observer``."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop ``application_observer``."""
    op.execute("DROP TABLE IF EXISTS application_observer")
