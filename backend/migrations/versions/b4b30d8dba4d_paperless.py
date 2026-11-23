"""paperless: the connection to Paperless and the record of the filings.

``paperless_settings`` is the single row with the address, the token and the four
switches of the integration. ``paperless_filing`` holds one row per file that the
platform files in Paperless, with the state of its job.

Idempotent. A fresh database already gets the tables from the ``create_all`` baseline
(0001), because the models sit in ``app.models``. A migrated database gets them through
``CREATE TABLE IF NOT EXISTS``.

The revision also grants ``admin.paperless`` and ``paperless.use`` to the ``admin``
role, so the role table shows them like every other permission. No other seeded role
gets them (§F/integrations/paperless/002524).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b4b30d8dba4d"
down_revision: str | None = "08e0c0134332"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS paperless_settings (
        id integer NOT NULL,
        base_url text,
        token text,
        file_protocols boolean NOT NULL DEFAULT false,
        protocols_since timestamptz,
        file_applications boolean NOT NULL DEFAULT false,
        applications_since timestamptz,
        file_plans boolean NOT NULL DEFAULT false,
        plans_since timestamptz,
        insert_enabled boolean NOT NULL DEFAULT false,
        CONSTRAINT pk_paperless_settings PRIMARY KEY (id),
        CONSTRAINT ck_paperless_settings_singleton CHECK (id = 1)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS paperless_filing (
        id uuid DEFAULT gen_random_uuid() NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        kind text NOT NULL,
        element_id uuid NOT NULL,
        source_id uuid NOT NULL,
        source_at timestamptz NOT NULL,
        application_id uuid,
        title text NOT NULL DEFAULT '',
        link text,
        actor text,
        state text NOT NULL DEFAULT 'pending',
        attempts integer NOT NULL DEFAULT 0,
        due_at timestamptz NOT NULL DEFAULT now(),
        last_error text,
        failed_at timestamptz,
        task_id text,
        uploaded_at timestamptz,
        document_id integer,
        filed_at timestamptz,
        replaced_at timestamptz,
        CONSTRAINT pk_paperless_filing PRIMARY KEY (id),
        CONSTRAINT ck_paperless_filing_kind CHECK (
            kind IN ('protocol','protocol_public','application','attachment','plan')
        ),
        CONSTRAINT ck_paperless_filing_state CHECK (
            state IN ('pending','uploaded','filed','failed')
        ),
        CONSTRAINT uq_paperless_filing_source UNIQUE (kind, source_id, source_at)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_paperless_filing_element ON paperless_filing (kind, element_id)",
    "CREATE INDEX IF NOT EXISTS ix_paperless_filing_application_id "
    "ON paperless_filing (application_id)",
    "CREATE INDEX IF NOT EXISTS ix_paperless_filing_open "
    "ON paperless_filing (due_at) WHERE state IN ('pending','uploaded')",
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, p.permission FROM role r "
        "CROSS JOIN (VALUES ('admin.paperless'), ('paperless.use')) AS p(permission) "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission IN ('admin.paperless', 'paperless.use')",
    "DROP TABLE IF EXISTS paperless_filing",
    "DROP TABLE IF EXISTS paperless_settings",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
