"""OAuth token: a selectable lifetime, including a never-expires option.

`access_expires_at` becomes nullable. NULL means the token never expires. The migration
also adds `access_ttl_seconds` to the authorization code and to the token. That column
keeps the selected lifetime for the refresh rotation. Idempotent through
`IF [NOT] EXISTS` and `DROP NOT NULL`.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_oauth_token_lifetime"
down_revision: str | None = "0007_oauth_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE oauth_token ALTER COLUMN access_expires_at DROP NOT NULL",
    "ALTER TABLE oauth_token ADD COLUMN IF NOT EXISTS access_ttl_seconds integer",
    "ALTER TABLE oauth_authorization_code ADD COLUMN IF NOT EXISTS access_ttl_seconds integer",
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE oauth_authorization_code DROP COLUMN IF EXISTS access_ttl_seconds",
    "ALTER TABLE oauth_token DROP COLUMN IF EXISTS access_ttl_seconds",
    # access_expires_at stays nullable, because the data can hold NULL after a downgrade.
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
