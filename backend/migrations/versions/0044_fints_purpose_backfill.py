"""fints_purpose_backfill: Zweck + Gegenkonto gestageter Umsätze neu normalisieren (#fints).

Vor dem Parser-Fix gestagete, **noch nicht gebuchte** Umsätze haben verklebte ?86-Subfelder
(„…0000794247ANZAHL 00000002", „30.06.2026siehe Anlage"), einen angehängten ``DATUM …UHR``-
Zusatz im Zweck und teils das Platzhalter-Kürzel „KRZL" als Gegenkonto. Diese Migration leitet
``purpose``/``counterparty_*`` für **offene** (``unmatched``/``suggested``) Zeilen einmalig aus
``raw_payload`` neu ab — über dieselbe Logik wie der Parser.

Idempotent + additiv: schreibt nur, wenn sich etwas ändert. Gebuchte Buchungen bleiben
unangetastet. Down-Migration: No-Op (ursprünglicher Rohwert nicht rekonstruierbar).
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
    from app.modules.budget.bank_import import (
        _normalize_purpose,
        _split_booking_time,
        mt940_counterparty,
    )

    conn = op.get_bind()
    # Alle Zeilen (auch gebuchte): Gegenkonto/Zweck sind reine Anzeige der gestageten Zeile; die
    # zugehörige Buchung trägt ihre eigenen Werte. Saubere Anzeige auch für ``matched``.
    rows = conn.execute(
        sa.text(
            "SELECT id, raw_payload, amount, purpose, counterparty_name, counterparty_iban "
            "FROM bank_statement_line"
        )
    ).all()
    for row in rows:
        raw = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        raw_purpose = raw.get("purpose")
        purpose, _ = _split_booking_time(_normalize_purpose(raw_purpose))
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
