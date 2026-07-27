"""Non-public agenda items and a second, public protocol PDF.

* `meeting_agenda_item.non_public` replaces the agenda item with a placeholder
  in the public protocol PDF. The numbering stays intact.
* `protocol.public_pdf_storage_key` is the MinIO key of the redacted public
  variant. It carries a value only when the meeting has at least one non-public
  agenda item.

All statements are idempotent (`IF [NOT] EXISTS`).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031_non_public_tops"
down_revision: str | None = "0030_pii_compliance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE meeting_agenda_item ADD COLUMN IF NOT EXISTS "
        "non_public boolean NOT NULL DEFAULT false"
    ),
    (
        "ALTER TABLE protocol ADD COLUMN IF NOT EXISTS "
        "public_pdf_storage_key text"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE protocol DROP COLUMN IF EXISTS public_pdf_storage_key",
    "ALTER TABLE meeting_agenda_item DROP COLUMN IF EXISTS non_public",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
