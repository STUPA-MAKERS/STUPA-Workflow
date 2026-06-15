"""Nicht-öffentliche TOPs + zweites (öffentliches) Protokoll-PDF.

* ``meeting_agenda_item.non_public`` — TOP wird im öffentlichen Protokoll-PDF
  durch einen Platzhalter ersetzt (Nummerierung bleibt erhalten).
* ``protocol.public_pdf_storage_key`` — MinIO-Key der redigierten öffentlichen
  Variante; nur befüllt, wenn die Sitzung mind. einen nicht-öffentlichen TOP hat.

Idempotent (``IF [NOT] EXISTS``).
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
