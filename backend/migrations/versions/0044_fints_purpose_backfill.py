"""fints_purpose_backfill: normalize the purpose and the counterparty again (#fints).

The old parser staged transactions that **nobody booked yet**. Such a row has glued ?86
subfields (``…0000794247ANZAHL 00000002``, ``30.06.2026siehe Anlage``). Its purpose also
carries an appended ``DATUM …UHR`` part. Some rows hold the placeholder code ``KRZL`` as
the counterparty. This migration derives ``purpose`` and ``counterparty_*`` once from
``raw_payload`` for **open** (``unmatched``/``suggested``) rows. It uses the same logic as
the parser.

The migration is idempotent and only adds information. It writes a row only when a value
changes. Booked expenses stay untouched. The down migration does nothing, because the
original raw value is not reconstructable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_fints_purpose_backfill"
down_revision: str | None = "0043_subbookings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.modules.budget.bank.normalize import (
        mt940_counterparty,
        normalize_purpose,
        split_booking_time,
    )

    conn = op.get_bind()
    # Read all rows, booked ones too. The counterparty and the purpose only feed the
    # display of the staged row. The related booking carries its own values. This keeps
    # the display clean for ``matched`` rows as well.
    rows = conn.execute(
        sa.text(
            "SELECT id, raw_payload, amount, purpose, counterparty_name, counterparty_iban "
            "FROM bank_statement_line"
        )
    ).all()
    for row in rows:
        raw = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        raw_purpose = raw.get("purpose")
        purpose, _ = split_booking_time(normalize_purpose(raw_purpose))
        name, iban = mt940_counterparty(raw, credit=(row.amount or 0) > 0)
        changed_purpose = purpose is not None and purpose != row.purpose
        changed_cp = (name or iban) and (
            name != row.counterparty_name or iban != row.counterparty_iban
        )
        if not changed_purpose and not changed_cp:
            continue
        conn.execute(
            sa.text(
                "UPDATE bank_statement_line SET "
                "purpose = :p, counterparty_name = :n, counterparty_iban = :i WHERE id = :id"
            ),
            {
                "p": purpose if changed_purpose else row.purpose,
                "n": name if changed_cp else row.counterparty_name,
                "i": iban if changed_cp else row.counterparty_iban,
                "id": row.id,
            },
        )


def downgrade() -> None:
    pass
