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

from alembic import op

revision: str = "0045_fints_dedup_staged"
down_revision: str | None = "0044_fints_purpose_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Gemeinsame, idempotente Routine (eine Logik, s. 0046). Bewusst KEINE Logik hier inline —
    # frühere Versionen dieser Revision liefen bereits; alembic überspringt sie. Die Korrektur
    # läuft als neue Revision 0046 erneut über dieselbe Funktion.
    from app.modules.budget.bank_maintenance import dedup_staged_lines

    dedup_staged_lines(op.get_bind())


def downgrade() -> None:
    pass
