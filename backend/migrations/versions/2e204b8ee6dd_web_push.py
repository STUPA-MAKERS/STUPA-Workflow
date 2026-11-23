"""web_push: the tables of web push (device subscriptions, push switches, VAPID key).

`push_subscription` holds one row per device of a person, `push_preference` the push
switch of a notification kind where it differs from the push default, and
`push_vapid_key` the single VAPID key pair that the platform makes at the first need.

Idempotent. A fresh database already gets the tables from the ``create_all`` baseline
(0001), because the models sit in ``app.models``. A migrated database gets them through
``CREATE TABLE IF NOT EXISTS``.

Revision ID: 2e204b8ee6dd
Revises: b7d3e1f0a9c4
Create Date: 2026-11-22 22:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2e204b8ee6dd"
down_revision: str | None = "b7d3e1f0a9c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS push_subscription (
        id uuid DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        principal_id uuid NOT NULL,
        endpoint text NOT NULL,
        p256dh text NOT NULL,
        auth text NOT NULL,
        label text NOT NULL DEFAULT '',
        last_success_at timestamptz,
        CONSTRAINT pk_push_subscription PRIMARY KEY (id),
        CONSTRAINT uq_push_subscription_endpoint UNIQUE (endpoint),
        CONSTRAINT fk_push_subscription_principal_id_principal
            FOREIGN KEY (principal_id) REFERENCES principal (id) ON DELETE CASCADE
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_push_subscription_principal_id "
        "ON push_subscription (principal_id)"
    ),
    """
    CREATE TABLE IF NOT EXISTS push_preference (
        principal_id uuid NOT NULL,
        kind text NOT NULL,
        enabled boolean NOT NULL DEFAULT true,
        CONSTRAINT pk_push_preference PRIMARY KEY (principal_id, kind),
        CONSTRAINT fk_push_preference_principal_id_principal
            FOREIGN KEY (principal_id) REFERENCES principal (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS push_vapid_key (
        id integer DEFAULT 1,
        created_at timestamptz NOT NULL DEFAULT now(),
        private_pem text NOT NULL,
        public_key text NOT NULL,
        CONSTRAINT pk_push_vapid_key PRIMARY KEY (id),
        CONSTRAINT ck_push_vapid_key_push_vapid_key_singleton CHECK (id = 1)
    )
    """,
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP TABLE IF EXISTS push_vapid_key",
    "DROP TABLE IF EXISTS push_preference",
    "DROP TABLE IF EXISTS push_subscription",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
