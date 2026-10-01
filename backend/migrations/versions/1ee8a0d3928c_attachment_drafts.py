"""Draft attachments of the wizard (Z4).

The upgrade:

1. makes `attachment.application_id` nullable. A draft upload of the wizard has no
   application yet.
2. adds `draft_token_hash` (bytea, the HMAC of the draft token) and
   `draft_expires_at` (timestamptz).
3. adds `CHECK (num_nonnulls(application_id, draft_token_hash) = 1)`: a row belongs
   to an application or to a draft token, never to both and never to neither. It
   also adds `CHECK ((draft_token_hash IS NULL) = (draft_expires_at IS NULL))`.
4. adds two partial indexes on the drafts only: one on `draft_expires_at` for the
   hourly purge, one on `draft_token_hash` for the token lookup.

There is no data migration. Every existing row has `application_id` and no draft
columns, so it satisfies both checks.

All steps are idempotent. A fresh database gets the columns, the checks and the
indexes from the `create_all` baseline (0001), because the model already declares
them.

The downgrade deletes the draft rows, because they cannot satisfy NOT NULL. Their
MinIO objects under `drafts/` stay as orphans, because a migration does not reach
the object storage. It then restores NOT NULL and drops the indexes, the checks and
the columns.

Revision ID: 1ee8a0d3928c
Revises: d5569d5542c6
Create Date: 2026-10-01 22:22:19.896748
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "1ee8a0d3928c"
down_revision: str | None = "d5569d5542c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_XOR = "ck_attachment_draft_xor_application"
_PAIRED = "ck_attachment_draft_columns_paired"
_IX_EXPIRES = "ix_attachment_draft_expires_at"
_IX_TOKEN = "ix_attachment_draft_token_hash"


def upgrade() -> None:
    op.execute("ALTER TABLE attachment ALTER COLUMN application_id DROP NOT NULL")
    op.execute("ALTER TABLE attachment ADD COLUMN IF NOT EXISTS draft_token_hash bytea")
    op.execute(
        "ALTER TABLE attachment ADD COLUMN IF NOT EXISTS draft_expires_at timestamptz"
    )
    op.execute(f"ALTER TABLE attachment DROP CONSTRAINT IF EXISTS {_XOR}")
    op.execute(
        f"ALTER TABLE attachment ADD CONSTRAINT {_XOR} "
        "CHECK (num_nonnulls(application_id, draft_token_hash) = 1)"
    )
    op.execute(f"ALTER TABLE attachment DROP CONSTRAINT IF EXISTS {_PAIRED}")
    op.execute(
        f"ALTER TABLE attachment ADD CONSTRAINT {_PAIRED} "
        "CHECK ((draft_token_hash IS NULL) = (draft_expires_at IS NULL))"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_IX_EXPIRES} ON attachment (draft_expires_at) "
        "WHERE draft_token_hash IS NOT NULL"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_IX_TOKEN} ON attachment (draft_token_hash) "
        "WHERE draft_token_hash IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DELETE FROM attachment WHERE application_id IS NULL")
    op.execute(f"DROP INDEX IF EXISTS {_IX_TOKEN}")
    op.execute(f"DROP INDEX IF EXISTS {_IX_EXPIRES}")
    op.execute(f"ALTER TABLE attachment DROP CONSTRAINT IF EXISTS {_PAIRED}")
    op.execute(f"ALTER TABLE attachment DROP CONSTRAINT IF EXISTS {_XOR}")
    op.execute("ALTER TABLE attachment DROP COLUMN IF EXISTS draft_expires_at")
    op.execute("ALTER TABLE attachment DROP COLUMN IF EXISTS draft_token_hash")
    op.execute("ALTER TABLE attachment ALTER COLUMN application_id SET NOT NULL")
