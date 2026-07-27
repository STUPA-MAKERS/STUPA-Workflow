"""fints_cp_backfill: derive the counterparty of staged rows from ``raw_payload`` (#fints).

The old parser staged transactions that **nobody booked yet**. Such a row often carries
only a short code in the name (for example ``KRZL``) and no IBAN. The real counterparty
sits in the SEPA raw fields inside ``raw_payload`` (``ABWE+``/``ABWA+`` → ``deviate_*``,
``IBAN+`` → ``gvc_applicant_iban``). This migration derives ``counterparty_name`` and
``counterparty_iban`` once for **open** (``unmatched``/``suggested``) rows. It uses the
same logic as the parser (``bank.normalize.mt940_counterparty``).

The migration only adds information. It updates a row only when the derivation returns
something new. CAMT rows and file rows without GVC fields stay untouched. The migration is
idempotent. It leaves rows of **booked** transactions alone on purpose, because the
booking step already cleans up their recipient. The down migration does nothing. The
original merged raw value is neither reconstructable nor worth keeping.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041_fints_cp_backfill"
down_revision: str | None = "0040_fints_lock_cooldown"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Reuse the parser logic. This runs once at deploy time, so the app import is safe.
    from app.modules.budget.bank.normalize import mt940_counterparty

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, raw_payload, amount, counterparty_name, counterparty_iban "
            "FROM bank_statement_line WHERE match_state IN ('unmatched', 'suggested')"
        )
    ).all()
    for row in rows:
        raw = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        name, iban = mt940_counterparty(raw, credit=(row.amount or 0) > 0)
        # Write only when the derivation returns a value AND that value differs.
        if (not name and not iban) or (
            name == row.counterparty_name and iban == row.counterparty_iban
        ):
            continue
        conn.execute(
            sa.text(
                "UPDATE bank_statement_line "
                "SET counterparty_name = :n, counterparty_iban = :i WHERE id = :id"
            ),
            {"n": name, "i": iban, "id": row.id},
        )


def downgrade() -> None:
    # The original raw value is gone, so no reverse mapping is possible.
    pass
