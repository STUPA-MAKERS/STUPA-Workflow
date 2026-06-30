"""fints_dedup_staged: bestehende doppelte Staging-Umsätze zusammenfassen + neu verschlüsseln.

Vor dem stabilen Idempotenz-Schlüssel (#fints-dedup) floss der **normalisierte Zweck** in den
Inhalts-Hash ein. Die Zweck-Normalisierung (Subfelder entkleben, ``DATUM…UHR`` entfernen) hat den
Hash verschoben → ein erneuter Abruf legte denselben Umsatz ein **zweites Mal** an.

Diese Migration räumt das einmalig auf, **nur für inhaltsgehashte** Zeilen (ohne bank-vergebene
Referenz):

* Gruppen gleicher (Konto, Wertstellung, Betrag, Gegen-IBAN, E2E, **kanonischer** Zweck) werden
  zusammengefasst — Dubletten im Zustand ``unmatched``/``suggested`` werden gelöscht (gebuchte
  ``matched``-Zeilen NIE).
* Die behaltene Zeile bekommt den **neuen kanonischen** Schlüssel (seq 0) → der nächste Abruf
  erkennt sie als bekannt (``ON CONFLICT DO NOTHING``) und dupliziert nicht erneut.

Konservativ: ref-verschlüsselte Zeilen (stabile Bank-Referenz) bleiben unangetastet; echte
Mehrfachzahlungen mit identischem Inhalt heilen beim nächsten Abruf von selbst wieder hoch
(seq 1+). Down-Migration: No-Op.
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
    from app.modules.budget.bank_import import _sha, canonical_purpose_key

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT l.id, l.account_id, l.value_date, l.amount, l.counterparty_iban, "
            "l.end_to_end_id, l.purpose, l.match_state, l.created_at, l.raw_payload, "
            "a.iban AS acc_iban "
            "FROM bank_statement_line l JOIN account a ON a.id = l.account_id "
            "ORDER BY l.account_id, l.created_at"
        )
    ).all()

    groups: dict[tuple[object, ...], list[sa.Row]] = {}
    for r in rows:
        raw = r.raw_payload if isinstance(r.raw_payload, dict) else {}
        bank_ref = str(raw.get("bank_reference") or raw.get("AcctSvcrRef") or "").strip()
        if bank_ref:
            continue  # stabil per Referenz verschlüsselt → nicht anfassen
        # Base wie assign_keys: OHNE counterparty_iban (parser-instabil) — sonst gruppiert die
        # alt-geparste gebuchte Zeile (iban="") nicht mit der neu-geparsten Dublette (iban gesetzt).
        base = (
            str(r.value_date or ""),
            str(r.amount),
            r.end_to_end_id or "",
            canonical_purpose_key(r.purpose),
        )
        groups.setdefault((r.account_id, *base), []).append(r)

    for key, grp in groups.items():
        account_id = key[0]
        base = key[1:]
        scope = grp[0].acc_iban or str(account_id)
        new_key = _sha(f"{scope}|{'|'.join(map(str, base))}|0")
        matched = [g for g in grp if g.match_state == "matched"]
        non_matched = [g for g in grp if g.match_state != "matched"]
        if matched:
            keeper_id = matched[0].id
            to_delete = non_matched  # Dubletten einer gebuchten Zeile
        else:
            keeper_id = non_matched[0].id
            to_delete = non_matched[1:]
        for d in to_delete:
            conn.execute(
                sa.text("DELETE FROM bank_statement_line WHERE id = :id"), {"id": d.id}
            )
        conn.execute(
            sa.text("UPDATE bank_statement_line SET idempotency_key = :k WHERE id = :id"),
            {"k": new_key, "id": keeper_id},
        )


def downgrade() -> None:
    pass
