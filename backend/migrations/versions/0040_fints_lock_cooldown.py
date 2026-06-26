"""fints_lock_cooldown: Sperr-Cooldown je FinTS-Credential (#fints-review).

Nach einer Bank-Sperre (FinTS 3938) oder einer Anmelde-/Signatur-Ablehnung (9340 u. a.)
darf nicht blind weiter-synct werden — jeder Versuch zählt auf das Bank-Fehlversuchskonto
ein und kann die Sperre bis zur Vollsperre verschärfen. ``fints_locked_until`` merkt sich
einen Cooldown; bis dahin verweigert der Service jeden Sync dieses Buchers für das Konto.

Reines additives ``ADD COLUMN`` (nullable, kein Default) — idempotent, sauberer Down-Round-
Trip.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0040_fints_lock_cooldown"
down_revision: str | None = "0039_fints_principal_creds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE account_fints_credential "
        "ADD COLUMN IF NOT EXISTS fints_locked_until timestamptz"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE account_fints_credential DROP COLUMN IF EXISTS fints_locked_until"
    )
