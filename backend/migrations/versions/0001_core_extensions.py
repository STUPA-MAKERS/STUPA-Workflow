"""core: extensions (pgcrypto, citext)

Revision ID: 0001_core_extensions
Revises:
Create Date: 2026-06-05 00:00:01

pgcrypto → `gen_random_uuid()` (UUID-PK-Defaults); citext → case-insensitive
E-Mail (`principal.email`, `applicant.email`). data-model §4.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_core_extensions"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS citext")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
