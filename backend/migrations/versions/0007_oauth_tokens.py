"""OAuth2-AS-Tabellen für den MCP-Login: Authorization-Codes + Access/Refresh-Token.

Idempotent: frische DBs erhalten die Tabellen bereits aus dem ``create_all``-Baseline
(0001), migrierte DBs tragen sie via ``CREATE TABLE IF NOT EXISTS`` nach. Token/Codes
werden nur als SHA-256-Hash gespeichert (Klartext nie persistiert).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_oauth_tokens"
down_revision: str | None = "0006_single_global_flow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS oauth_authorization_code (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        code_hash bytea NOT NULL UNIQUE,
        principal_id uuid NOT NULL REFERENCES principal(id) ON DELETE CASCADE,
        client_id text NOT NULL,
        redirect_uri text NOT NULL,
        code_challenge text NOT NULL,
        scope text NOT NULL,
        expires_at timestamptz NOT NULL,
        used_at timestamptz
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_token (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        principal_id uuid NOT NULL REFERENCES principal(id) ON DELETE CASCADE,
        client_id text NOT NULL,
        access_token_hash bytea NOT NULL UNIQUE,
        refresh_token_hash bytea UNIQUE,
        scope text NOT NULL,
        access_expires_at timestamptz NOT NULL,
        refresh_expires_at timestamptz,
        revoked_at timestamptz
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_oauth_token_principal_id ON oauth_token (principal_id)",
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP TABLE IF EXISTS oauth_token",
    "DROP TABLE IF EXISTS oauth_authorization_code",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
