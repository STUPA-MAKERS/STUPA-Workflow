"""fints_dedup_staged: re-importierte Dubletten gestageter Umsätze aus den ROHDATEN auflösen.

Vor dem rohdaten-basierten Idempotenz-Schlüssel (#fints-raw) flossen parser-abgeleitete Felder
(``counterparty_iban``, normalisierter Zweck) in den Hash ein. Eine Parser-Verbesserung verschob
ihn → ein erneuter Abruf legte denselben Bank-Umsatz erneut an (typisch: gebuchte ``matched``-Zeile
+ neu geparste ``unmatched``-Dublette).

Diese Migration vergleicht ausschließlich über ``raw_dedup_base`` (Wertstellung, Betrag, E2E,
kanonischer Roh-Zweck, kanonischer Roh-Gegenkonto-Block — alles parser-unabhängig aus
``raw_payload``). Zeilen mit gleicher Roh-Basis sind derselbe Umsatz: die **gebuchte** Zeile bleibt
(Buchung unberührt; die Anzeige wird ohnehin live aus den Rohdaten aufgelöst), sonst die älteste;
ungebuchte Kopien werden gelöscht. Gruppen ohne gebuchte Zeile UND ohne echte Roh-Dublette bleiben
unangetastet — fünf echte 80-€-Zahlungen am selben Tag haben unterschiedliche Roh-Auftraggeber und
kollabieren NICHT. Die behaltene Zeile bekommt den neuen Roh-Schlüssel. Down-Migration: No-Op.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_fints_dedup_staged"
down_revision: str | None = "0044_fints_purpose_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.modules.budget.bank_import import _sha, raw_dedup_base

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT l.id, l.account_id, l.value_date, l.amount, l.end_to_end_id, "
            "l.match_state, l.created_at, l.raw_payload, a.iban AS acc_iban "
            "FROM bank_statement_line l JOIN account a ON a.id = l.account_id "
            "ORDER BY l.account_id, l.created_at"
        )
    ).all()

    groups: dict[tuple[object, ...], list[sa.Row]] = {}
    for r in rows:
        base = raw_dedup_base(r.value_date, r.amount, r.end_to_end_id, r.raw_payload)
        groups.setdefault((r.account_id, *base), []).append(r)

    for key, grp in groups.items():
        if len(grp) < 2:
            continue  # eindeutiger Umsatz — nichts zu tun
        matched = [g for g in grp if g.match_state == "matched"]
        non_matched = [g for g in grp if g.match_state != "matched"]
        if not non_matched:
            continue  # nur gebuchte (kein Re-Import) — nicht anfassen
        keeper = matched[0] if matched else non_matched[0]
        for g in non_matched:
            if g.id == keeper.id:
                continue
            conn.execute(
                sa.text("DELETE FROM bank_statement_line WHERE id = :id"), {"id": g.id}
            )
        scope = keeper.acc_iban or str(keeper.account_id)
        new_key = _sha(f"{scope}|{'|'.join(str(p) for p in key[1:])}|0")
        conn.execute(
            sa.text("UPDATE bank_statement_line SET idempotency_key = :k WHERE id = :id"),
            {"k": new_key, "id": keeper.id},
        )


def downgrade() -> None:
    pass
