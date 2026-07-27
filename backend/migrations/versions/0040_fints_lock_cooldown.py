"""fints_lock_cooldown: a lock cooldown per FinTS credential (#fints-review).

After a bank lock (FinTS 3938) or a rejected login or signature (9340 and others), the
service must not sync on blindly. Every attempt counts against the failed-attempt counter
of the bank and can escalate the lock to a full lock. ``fints_locked_until`` holds a
cooldown. Until that time the service refuses every sync of this booker for the account.

The migration only adds a column (nullable, no default). It is idempotent and has a clean
down round trip.
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
