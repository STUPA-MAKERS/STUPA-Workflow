"""CAMT.052/053-Auszüge (XML) → :class:`~.statement.StatementLine` (#fints).

Namespace-tolerant (über local-name) und versions-tolerant (beliebige
``camt.05x.001.yy``). **Sammelbuchungen** — ein ``Ntry`` mit mehreren ``TxDtls``
(Sparkasse: „DATEI-NR. … ANZAHL …") — werden in **Einzelumsätze aufgeteilt**
(#fints-batch): je ``TxDtls`` eine Zeile mit eigenem Betrag/Zweck/Gegenkonto.
Nur wenn die Teilbeträge den Buchungsbetrag exakt ergeben, wird gesplittet;
sonst bleibt es (konservativ) bei einer Zeile mit dem Gesamtbetrag.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from app.modules.budget.bank.normalize import (
    clean,
    skip_notprovided,
    split_booking_time,
    split_leading_iban,
)
from app.modules.budget.bank.statement import (
    StatementBalance,
    StatementLine,
    StatementParseError,
    sane_amount,
)


def parse_camt(data: bytes) -> list[StatementLine]:
    """CAMT-Auszug (Report ``camt.052`` oder Statement ``camt.053``) → Umsätze.

    :raises StatementParseError: kein/kaputtes CAMT-XML oder keine verwertbaren Einträge."""
    try:
        root = ET.fromstring(data)  # noqa: S314 - eigener Auszug, keine externen Entities
    except ET.ParseError as exc:
        raise StatementParseError(f"unparseable CAMT XML: {exc}") from exc

    entries = _findall_local(root, "Ntry")
    if not entries:
        raise StatementParseError("CAMT XML contained no entries (Ntry)")

    lines: list[StatementLine] = []
    for ntry in entries:
        lines.extend(_lines_from_entry(ntry))
    if not lines:
        raise StatementParseError("CAMT XML contained no usable entries")
    return lines


@dataclass(slots=True)
class _Entry:
    """Vorverdaute ``Ntry``-Fakten, die jede daraus erzeugte Zeile teilt."""

    amount: Decimal  # vorzeichenbehaftet (inkl. Storno-Umkehr)
    orig_credit: bool  # CdtDbtInd des Eintrags (Original-Richtung)
    reversal: bool
    currency: str
    booking_date: date | None
    value_date: date | None
    bank_ref: str | None


def _entry_facts(ntry: ET.Element) -> _Entry | None:
    """Betrag/Richtung/Storno/Daten eines ``Ntry`` lesen — ``None`` = unbrauchbar."""
    amt_el = _find_local(ntry, "Amt")
    if amt_el is None or not (amt_el.text or "").strip():
        return None
    try:
        magnitude = Decimal((amt_el.text or "").strip())
    except (InvalidOperation, ValueError):
        return None
    # Richtung **explizit** verlangen: ohne klares CRDT/DBIT ist die wirtschaftliche
    # Richtung unbekannt — nicht still als Abgang annehmen (#fints-review).
    ind = (_find_text_local(ntry, "CdtDbtInd") or "").upper()
    if ind.startswith("CRDT"):
        orig_credit = True
    elif ind.startswith("DBIT"):
        orig_credit = False
    else:
        return None
    # Storno (``RvslInd=true``) kehrt die wirtschaftliche Richtung um (Rückbuchung).
    reversal = (_find_text_local(ntry, "RvslInd") or "").strip().lower() in ("true", "1")
    credit = (not orig_credit) if reversal else orig_credit
    # CAMT ``<Amt>`` ist spec-gemäß ≥ 0; ein negativer Wert würde das Vorzeichen unten
    # erneut kippen → defensiv den Betrag entkoppeln (Richtung kommt nur aus dem Indikator).
    amount = sane_amount(abs(magnitude) if credit else -abs(magnitude))
    return _Entry(
        amount=amount,
        orig_credit=orig_credit,
        reversal=reversal,
        currency=(amt_el.get("Ccy") or "EUR").upper(),
        booking_date=_camt_date(_find_local(ntry, "BookgDt")),
        value_date=_camt_date(_find_local(ntry, "ValDt")),
        bank_ref=clean(_find_text_local(ntry, "AcctSvcrRef")),
    )


def _lines_from_entry(ntry: ET.Element) -> list[StatementLine]:
    """Ein ``Ntry`` → 1 Zeile (Einzelbuchung) oder n Zeilen (aufgeteilte Sammelbuchung)."""
    entry = _entry_facts(ntry)
    if entry is None:
        return []
    tx_details = _findall_local(ntry, "TxDtls")
    if len(tx_details) >= 2:
        split = _split_batch(ntry, entry, tx_details)
        if split is not None:
            return split
    scope = tx_details[0] if tx_details else ntry
    return [_line_from_scope(scope, ntry, entry, amount=entry.amount, bank_ref=entry.bank_ref)]


def _split_batch(
    ntry: ET.Element, entry: _Entry, tx_details: list[ET.Element]
) -> list[StatementLine] | None:
    """Sammelbuchung in Einzelumsätze auflösen — oder ``None``, wenn das nicht sicher geht.

    Sicher heißt: jede ``TxDtls`` trägt einen eigenen ``TxAmt`` in der Eintrags-Währung und
    die (vorzeichenbehafteten) Teilbeträge summieren sich exakt auf den Buchungsbetrag —
    sonst würde der Split Beträge erfinden (z. B. bei Brutto/Netto-Abweichung durch Entgelte).
    """
    lines: list[StatementLine] = []
    total = Decimal("0")
    for tx in tx_details:
        amount = _tx_amount(tx, entry)
        if amount is None:
            return None
        # Bank-Referenz je Teil-Transaktion (falls vorhanden). Die Eintrags-Referenz ist für
        # alle Teile identisch und darf NICHT verwendet werden — sonst kollabierten alle
        # Teilzeilen auf denselben Idempotenz-Schlüssel (#fints-batch).
        tx_ref = clean(_find_text_local(_find_local(tx, "Refs"), "AcctSvcrRef"))
        lines.append(_line_from_scope(tx, ntry, entry, amount=amount, bank_ref=tx_ref))
        total += amount
    if total != entry.amount:
        return None
    batch_meta = {
        "batch": "true",
        "batch_count": str(len(tx_details)),
        "batch_total": str(entry.amount),
        **({"batch_ref": entry.bank_ref} if entry.bank_ref else {}),
    }
    for line in lines:
        line.raw.update(batch_meta)
    return lines


def _tx_amount(tx: ET.Element, entry: _Entry) -> Decimal | None:
    """Vorzeichenbehafteter Betrag einer Teil-Transaktion (``AmtDtls/TxAmt/Amt``).

    ``None``, wenn Betrag/Währung fehlen oder nicht zur Eintrags-Währung passen. Die Richtung
    kommt aus dem ``CdtDbtInd`` der Teil-Transaktion, sonst vom Eintrag; ein Eintrags-Storno
    kehrt sie um (wie beim ungeteilten Eintrag)."""
    tx_amt = _find_local(tx, "TxAmt")
    amt_el = _find_local(tx_amt, "Amt") if tx_amt is not None else None
    if amt_el is None or not (amt_el.text or "").strip():
        return None
    if (amt_el.get("Ccy") or entry.currency).upper() != entry.currency:
        return None
    try:
        magnitude = Decimal((amt_el.text or "").strip())
    except (InvalidOperation, ValueError):
        return None
    ind = (_find_text_local(tx, "CdtDbtInd") or "").upper()
    if ind.startswith("CRDT"):
        orig_credit = True
    elif ind.startswith("DBIT"):
        orig_credit = False
    else:
        orig_credit = entry.orig_credit
    credit = (not orig_credit) if entry.reversal else orig_credit
    return sane_amount(abs(magnitude) if credit else -abs(magnitude))


def _line_from_scope(
    scope: ET.Element,
    ntry: ET.Element,
    entry: _Entry,
    *,
    amount: Decimal,
    bank_ref: str | None,
) -> StatementLine:
    """Eine Zeile aus einem Detail-Scope (``TxDtls`` bzw. das ``Ntry`` selbst) bauen."""
    credit = amount > 0
    # Gegenpartei folgt der **ursprünglichen** Richtung (Dbtr/Cdtr stehen im XML zur
    # Originalrichtung) — bei Gutschrift der Debitor (Zahler), sonst der Kreditor.
    orig_credit = (not credit) if entry.reversal else credit
    party_tag, acct_tag = ("Dbtr", "DbtrAcct") if orig_credit else ("Cdtr", "CdtrAcct")
    party = _find_local(scope, party_tag)
    acct = _find_local(scope, acct_tag)
    cp_name, cp_iban = split_leading_iban(
        _find_text_local(party, "Nm") if party is not None else None,
        _find_text_local(acct, "IBAN") if acct is not None else None,
    )
    purpose, booking_time = split_booking_time(_purpose_text(scope, ntry))
    raw = {
        "creditDebit": "CRDT" if entry.orig_credit else "DBIT",
        **({"reversal": "true"} if entry.reversal else {}),
        **({"booking_time": booking_time} if booking_time else {}),
        # Roh-Zweck mitschreiben (#fints-raw): speist ``resolve_purpose`` und macht den
        # Inhalts-Hash-Schlüssel aussagekräftig (Zeilen ohne Bank-Referenz).
        **({"purpose": purpose} if purpose else {}),
    }
    return StatementLine(
        amount=amount,
        currency=entry.currency,
        booking_date=entry.booking_date,
        value_date=entry.value_date,
        purpose=purpose,
        counterparty_name=cp_name,
        counterparty_iban=cp_iban,
        end_to_end_id=clean(skip_notprovided(_find_text_local(scope, "EndToEndId"))),
        reference=clean(_find_text_local(scope, "InstrId")),
        bank_ref=bank_ref,
        raw=raw,
    )


def _purpose_text(scope: ET.Element, ntry: ET.Element) -> str | None:
    """Verwendungszweck eines Scopes: alle ``Ustrd``-Zeilen (Banken teilen lange Zwecke auf
    mehrere Elemente) zusammengesetzt; ohne ``Ustrd`` die ``AddtlNtryInf`` des Eintrags
    (Sparkasse legt dort z. B. „SAMMELUEBERWEISUNG DATEI-NR. …" ab)."""
    parts = [t for el in _findall_local(scope, "Ustrd") if (t := clean(el.text))]
    if parts:
        return " ".join(parts)
    return clean(_find_text_local(ntry, "AddtlNtryInf"))


# ------------------------------------------------------------------------ balance
def camt_closing_balance(data: bytes) -> StatementBalance | None:
    """CAMT-Schlusssaldo: ``<Bal>`` mit Code ``CLBD`` (Closing Booked); Vorzeichen aus
    ``CdtDbtInd``. Fällt auf ``CLAV`` (Closing Available) zurück, wenn kein CLBD da ist."""
    try:
        root = ET.fromstring(data)  # noqa: S314 - eigener Auszug, keine externen Entities
    except ET.ParseError:
        return None
    by_code: dict[str, ET.Element] = {}
    for bal in _findall_local(root, "Bal"):
        code = (_find_text_local(bal, "Cd") or "").upper()
        if code:
            # Bei mehreren <Stmt> (mehrtägiger Export) gewinnt der LETZTE Schlusssaldo (#review).
            by_code[code] = bal
    # `Element or Element` triggert die ElementTree-Truthiness-Deprecation → explizit prüfen.
    chosen = by_code.get("CLBD")
    if chosen is None:
        chosen = by_code.get("CLAV")
    if chosen is None:
        return None
    amt_el = _find_local(chosen, "Amt")
    if amt_el is None or not (amt_el.text or "").strip():
        return None
    try:
        magnitude = sane_amount(Decimal((amt_el.text or "").strip()))
    except (InvalidOperation, ValueError, StatementParseError):
        return None
    ind = (_find_text_local(chosen, "CdtDbtInd") or "").upper()
    amount = -abs(magnitude) if ind.startswith("DBIT") else abs(magnitude)
    return StatementBalance(
        amount=amount,
        currency=(amt_el.get("Ccy") or "EUR").upper(),
        as_of=_camt_date(_find_local(chosen, "Dt")),
    )


# -------------------------------------------------------------------- XML helpers
def _local(tag: str) -> str:
    """Lokaler Tag-Name ohne ``{namespace}``-Präfix."""
    return tag.rsplit("}", 1)[-1]


def _find_local(el: ET.Element | None, name: str) -> ET.Element | None:
    if el is None:
        return None
    for child in el.iter():
        if child is not el and _local(child.tag) == name:
            return child
    return None


def _findall_local(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el.iter() if _local(c.tag) == name]


def _find_text_local(el: ET.Element | None, name: str) -> str | None:
    found = _find_local(el, name)
    return found.text if found is not None else None


def _camt_date(el: ET.Element | None) -> date | None:
    """CAMT ``BookgDt``/``ValDt`` → ``date`` (``Dt`` = YYYY-MM-DD, oder ``DtTm``)."""
    if el is None:
        return None
    raw = _find_text_local(el, "Dt") or _find_text_local(el, "DtTm")
    if not raw or len(raw) < 10:
        return None
    try:
        return date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))
    except ValueError:
        return None
