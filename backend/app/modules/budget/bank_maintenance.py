"""Einmalige Aufräum-Routinen für gestagete Bank-Umsätze (#fints-dedup).

Getrennt von :mod:`bank_service` (async ORM), weil Migrationen mit einer **synchronen**
``Connection`` (``op.get_bind()``) arbeiten. Reine, idempotente Daten-Korrektur — von den
Migrationen 0045/0046 aufgerufen (eine Logik, kein dupliziertes Migrations-Skript)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection


def dedup_staged_lines(conn: Connection) -> int:
    """Re-importierte Dubletten gestageter Umsätze zusammenfassen — Vergleich **rein über die
    Rohdaten** (:func:`bank_import.raw_dedup_base`, parser-unabhängig).

    Pro Konto + gleicher Roh-Basis: ist eine **gebuchte** (``matched``) Zeile dabei (oder, ohne
    gebuchte, die älteste), bleibt sie erhalten; die übrigen **ungebuchten** exakten Dubletten
    werden gelöscht. Die behaltene Zeile bekommt den neuen Roh-Schlüssel, damit der nächste Abruf
    sie als bekannt erkennt. Gebuchte Zeilen werden nie gelöscht; Gruppen ohne Dublette bleiben
    unangetastet (echte Einzelzahlungen mit unterschiedlichem Roh-Auftraggeber/-Zweck/-Zeitstempel
    fallen NICHT zusammen). Idempotent. Liefert die Anzahl gelöschter Zeilen.
    """
    from app.modules.budget.bank_import import _sha, raw_dedup_base

    rows = conn.execute(
        text(
            "SELECT l.id, l.account_id, l.value_date, l.amount, l.end_to_end_id, "
            "l.match_state, l.created_at, l.raw_payload, a.iban AS acc_iban "
            "FROM bank_statement_line l JOIN account a ON a.id = l.account_id "
            "ORDER BY l.account_id, l.created_at"
        )
    ).all()

    groups: dict[tuple[object, ...], list] = {}
    for r in rows:
        base = raw_dedup_base(r.value_date, r.amount, r.end_to_end_id, r.raw_payload)
        groups.setdefault((r.account_id, *base), []).append(r)

    deleted = 0
    for key, grp in groups.items():
        if len(grp) < 2:
            continue
        non_matched = [g for g in grp if g.match_state != "matched"]
        if not non_matched:
            continue  # nur gebuchte (kein Re-Import) — nicht anfassen
        matched = [g for g in grp if g.match_state == "matched"]
        keeper = matched[0] if matched else non_matched[0]
        for g in non_matched:
            if g.id == keeper.id:
                continue
            conn.execute(
                text("DELETE FROM bank_statement_line WHERE id = :id"), {"id": g.id}
            )
            deleted += 1
        scope = keeper.acc_iban or str(keeper.account_id)
        new_key = _sha(f"{scope}|{'|'.join(str(p) for p in key[1:])}|0")
        conn.execute(
            text("UPDATE bank_statement_line SET idempotency_key = :k WHERE id = :id"),
            {"k": new_key, "id": keeper.id},
        )
    return deleted
