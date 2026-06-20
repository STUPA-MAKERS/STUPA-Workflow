"""drop_fully_bound: Feature »Kostenstelle komplett als gebunden« entfernt.

Die Spalte ``budget.fully_bound`` (eingeführt in 0004) wird entfernt — Kostenstellen
zählen wieder ausschließlich ihre echten Anträge/Ausgaben (kein synthetisches
Voll-Binden mehr). Idempotent (``IF EXISTS``); Down-Round-Trip stellt die Spalte
(NOT NULL DEFAULT false) wieder her.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0036_drop_fully_bound"
down_revision: str | None = "0035_fints_bank_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE budget DROP COLUMN IF EXISTS fully_bound")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE budget ADD COLUMN IF NOT EXISTS "
        "fully_bound boolean NOT NULL DEFAULT false"
    )
