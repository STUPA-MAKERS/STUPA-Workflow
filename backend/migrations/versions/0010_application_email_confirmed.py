"""Application: `email_confirmed_at` (a guest submission needs a confirmation).

An application from a user who is not logged in stays invisible until that user
confirms the email through a magic link. The platform discards an unconfirmed
application after 12 h. Existing applications count as confirmed, so the backfill sets
`email_confirmed_at` to `created_at`. Without that backfill they would go invisible. A
new guest application starts with NULL. Idempotent through `IF NOT EXISTS`.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_application_email_confirmed"
down_revision: str | None = "0009_transition_color"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE application ADD COLUMN IF NOT EXISTS email_confirmed_at timestamptz",
    "UPDATE application SET email_confirmed_at = created_at WHERE email_confirmed_at IS NULL",
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE application DROP COLUMN IF EXISTS email_confirmed_at",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
