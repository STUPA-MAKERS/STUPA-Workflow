"""Public protocols: the gremium flag and the public version of a protocol.

The upgrade adds:

1. `gremium.protocols_public` (bool, default false). When it is true, the final
   protocols of the gremium appear without login on the public protocols page.
2. `protocol.public_withheld` (bool, default false). It holds back one protocol
   of a public gremium.
3. `protocol.public_content` (JSONB), `protocol.public_search_text` (text) and
   `protocol.public_pdf_size` (integer). They hold the snapshot of the public
   version that the public API serves. They stay NULL until the finalization or
   the backfill job writes them, so no existing protocol becomes public by this
   migration.
4. `protocol.public_render_failures` (integer, default 0). It counts the
   permanent failures of the public build, so the hourly heal job can skip a
   protocol that always fails.

All statements are idempotent (`ADD COLUMN IF NOT EXISTS`). A fresh database
already gets the columns from the `create_all` baseline (0001).

The downgrade drops the columns.

Revision ID: bf0309071fb4
Revises: ed7ea60b3551
Create Date: 2026-10-07 12:29:08.261685
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "bf0309071fb4"
down_revision: str | None = "ed7ea60b3551"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE gremium ADD COLUMN IF NOT EXISTS protocols_public "
        "boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE protocol ADD COLUMN IF NOT EXISTS public_withheld "
        "boolean NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE protocol ADD COLUMN IF NOT EXISTS public_content jsonb")
    op.execute("ALTER TABLE protocol ADD COLUMN IF NOT EXISTS public_search_text text")
    op.execute("ALTER TABLE protocol ADD COLUMN IF NOT EXISTS public_pdf_size integer")
    op.execute(
        "ALTER TABLE protocol ADD COLUMN IF NOT EXISTS public_render_failures "
        "integer NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE protocol DROP COLUMN IF EXISTS public_render_failures")
    op.execute("ALTER TABLE protocol DROP COLUMN IF EXISTS public_pdf_size")
    op.execute("ALTER TABLE protocol DROP COLUMN IF EXISTS public_search_text")
    op.execute("ALTER TABLE protocol DROP COLUMN IF EXISTS public_content")
    op.execute("ALTER TABLE protocol DROP COLUMN IF EXISTS public_withheld")
    op.execute("ALTER TABLE gremium DROP COLUMN IF EXISTS protocols_public")
