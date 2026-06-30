"""fints_cp_backfill: Gegenkonto gestageter Umsätze aus ``raw_payload`` neu ableiten (#fints).

Vor dem Parser-Fix gestagete, **noch nicht gebuchte** Umsätze tragen im Namen oft nur ein
Kürzel (z. B. „KRZL") und keine IBAN, obwohl der echte Gegenpart in den SEPA-Rohfeldern
(``ABWE+``/``ABWA+`` → ``deviate_*``, ``IBAN+`` → ``gvc_applicant_iban``) im ``raw_payload``
steckt. Diese Migration leitet ``counterparty_name``/``counterparty_iban`` für **offene**
(``unmatched``/``suggested``) Zeilen einmalig neu ab — über dieselbe Logik wie der Parser
(``bank_import.mt940_counterparty``).

Rein additiv: aktualisiert nur Zeilen, bei denen die Ableitung etwas Neues liefert; CAMT-/
Datei-Zeilen ohne GVC-Felder bleiben unangetastet. Idempotent. Schon **gebuchte** Buchungen
werden bewusst NICHT angefasst (deren Empfänger wird beim Buchen bereits bereinigt). Down-
Migration: No-Op — der ursprüngliche, verschmolzene Rohwert ist weder rekonstruierbar noch
erhaltenswert.
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
    # Parser-Logik wiederverwenden (läuft einmalig beim Deploy → App-Import unkritisch).
    from app.modules.budget.bank_import import mt940_counterparty

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
        # Nur schreiben, wenn die Ableitung etwas liefert UND sich etwas ändert.
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
    # Kein Rück-Mapping möglich (ursprünglicher Rohwert nicht gespeichert) — No-Op.
    pass
