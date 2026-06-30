"""account_balance: letzten Bank-Kontostand je Konto speichern (#fints-konten).

Beim FinTS-Sync (HKSAL-Saldo) bzw. Datei-Import (``:62F:``/CLBD-Schlusssaldo) wird der
Kontostand + Stichtag am Konto abgelegt — reiner Anzeige-/Abgleich-Wert für den Konten-Tab,
NICHT Teil der Budget-Rechnung. Additiv + idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0042_account_balance"
down_revision: str | None = "0041_fints_cp_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_last_balance numeric(14, 2)")
    op.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_balance_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE account DROP COLUMN IF EXISTS fints_balance_at")
    op.execute("ALTER TABLE account DROP COLUMN IF EXISTS fints_last_balance")
