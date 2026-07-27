"""applicant_session: server-side magic-link sessions (security.md §1).

The migration makes the applicant magic-link token **stateful**, like ``auth_session``.
The browser holds only a signed, opaque ``sid``. The server keeps ``application_id`` and
``scope``. An attacker can no longer forge a token from ``SESSION_SECRET`` alone, because
the token needs an existing row. The server can also revoke a token. A logout deletes the
row. The kill switch sets ``revoked_at``, for example on anonymization.

The migration is idempotent (``IF NOT EXISTS``) and has a clean down round trip. On a
fresh schema ``Base.metadata.create_all`` (0001/0002) creates the table anyway.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0037_applicant_session"
down_revision: str | None = "0036_drop_fully_bound"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS applicant_session (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        sid text NOT NULL UNIQUE,
        application_id uuid NOT NULL REFERENCES application (id) ON DELETE CASCADE,
        scope text NOT NULL,
        expires_at timestamptz NOT NULL,
        revoked_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_applicant_session_application_id "
    "ON applicant_session (application_id)",
)

_DOWNGRADE: tuple[str, ...] = ("DROP TABLE IF EXISTS applicant_session",)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
