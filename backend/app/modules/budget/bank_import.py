"""Kontoauszug-Parser (#fints): MT940 (.sta) und CAMT.053 (XML) → normalisierte Umsätze.

Reine Funktionen (kein DB-/Netz-I/O). Beide Quellen — der FinTS-Abruf (liefert MT940
bzw. CAMT) **und** der manuelle Datei-Import — münden in dieselbe :class:`StatementLine`,
sodass Matcher/Service quellen-agnostisch bleiben. ``mt940`` wird **lazy** importiert
(transitiv über ``fints``); CAMT wird mit der Standard-Lib (ElementTree) namespace-tolerant
geparst.

``amount`` ist **vorzeichenbehaftet**: > 0 Eingang (income), < 0 Ausgang (expense). Der
Service leitet daraus ``kind`` + ``abs(amount)`` für die Buchung ab.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

# Obergrenze = DB-Spalte ``numeric(12, 2)`` — größere Beträge aus untrusted Dateien sauber
# abweisen statt numeric-overflow beim INSERT (vgl. invoice_import #sec-audit).
_MAX_AMOUNT = Decimal("9999999999.99")


class StatementParseError(ValueError):
    """Datei ist weder gültiges MT940 noch CAMT.053 (oder leer/kaputt)."""


@dataclass(slots=True)
class StatementLine:
    """Ein normalisierter Kontoumsatz (quellen-agnostisch)."""

    amount: Decimal  # vorzeichenbehaftet: > 0 Eingang, < 0 Ausgang
    currency: str = "EUR"
    booking_date: date | None = None
    value_date: date | None = None
    purpose: str | None = None
    counterparty_name: str | None = None
    counterparty_iban: str | None = None
    end_to_end_id: str | None = None
    reference: str | None = None
    # Bank-vergebene eindeutige Referenz (CAMT ``AcctSvcrRef`` / MT940 ``bank_reference``)
    # — bevorzugter Idempotenz-Schlüssel; sonst Inhalts-Hash (s. :func:`assign_keys`).
    bank_ref: str | None = None
    # Vom Service gesetzt (nach :func:`assign_keys`).
    idempotency_key: str = ""
    # Roh-Felder zur Nachvollziehbarkeit (in ``raw_payload`` persistiert).
    raw: dict[str, str] = field(default_factory=dict)


def _sane_amount(value: Decimal) -> Decimal:
    """Betrag auf gültigen Bereich + Cent-Granularität prüfen (Vorzeichen bleibt erhalten)."""
    if not value.is_finite() or abs(value) > _MAX_AMOUNT:
        raise StatementParseError(f"amount out of range: {value}")
    # Sub-Cent-Präzision (z. B. CAMT ``100.005``) NICHT still auf 2 Stellen runden — das
    # würde Beträge gegenüber der Quelle verfälschen; klar ablehnen (#fints-review).
    if value != value.quantize(Decimal("0.01")):
        raise StatementParseError(f"amount has sub-cent precision: {value}")
    return value


# ----------------------------------------------------------------------- MT940
def parse_mt940(data: bytes) -> list[StatementLine]:
    """MT940-Kontoauszug (z. B. Sparkasse ``.sta``) → Umsätze.

    :raises StatementParseError: nicht parsebar / kein MT940."""
    import mt940  # lazy (transitiv über fints)

    text = _decode(data)
    try:
        transactions = mt940.models.Transactions()
        transactions.parse(text)
    except Exception as exc:  # pragma: no cover - mt940 wirft diverse Fehler bei kaputten Auszügen
        raise StatementParseError(f"unparseable MT940: {exc}") from exc

    lines = lines_from_mt940_transactions(transactions)
    if not lines:
        raise StatementParseError("MT940 contained no transactions")
    return lines


def lines_from_mt940_transactions(transactions: object) -> list[StatementLine]:
    """``mt940``-Transaktionen (auch der FinTS-Abruf liefert diese) → Umsätze.

    Geteilt von :func:`parse_mt940` (Datei-Import) und dem FinTS-Client (Live-Abruf),
    damit beide Pfade identisch normalisieren."""
    lines: list[StatementLine] = []
    for tx in transactions:  # type: ignore[attr-defined]
        line = _line_from_mt940_data(tx.data)
        if line is not None:
            lines.append(line)
    return lines


def _line_from_mt940_data(d: dict[str, object]) -> StatementLine | None:
    """Eine ``mt940``-Transaktions-``data``-Map → :class:`StatementLine` (oder ``None``)."""
    amount_obj = d.get("amount")
    magnitude = getattr(amount_obj, "amount", None)
    if magnitude is None:
        return None
    # Vorzeichen **explizit** aus dem MT940-Status ableiten (#fints-review): die ``mt940``-
    # Lib negiert NUR bei status == 'D', lässt Storno-Marker 'RC'/'RD' aber unverändert
    # positiv → eine Lastschrift-Rückgabe (RC = Storno einer Gutschrift = Abgang) käme sonst
    # als Eingang an. Abgang: D / RC. Eingang: C / RD. Unbekannt → Lib-Vorzeichen behalten.
    raw_amount = Decimal(str(magnitude))
    status = str(d.get("status") or "").upper()
    if status in ("D", "RC"):
        raw_amount = -abs(raw_amount)
    elif status in ("C", "RD"):
        raw_amount = abs(raw_amount)
    amount = _sane_amount(raw_amount)
    cp_name, cp_iban = _mt940_counterparty(d, credit=raw_amount > 0)
    # Sparkassen-MT940 hängt die Buchungs-Uhrzeit als ``…DATUM dd.mm.yyyy, hh.mm UHR`` an den
    # Verwendungszweck — vom eigentlichen Zweck lösen (sauberer Zweck) und die Zeit für die
    # spätere Buchungs-Anmerkung in ``raw`` ablegen (#fints).
    purpose, booking_time = _split_booking_time(_clean(d.get("purpose")))
    raw = {k: str(v) for k, v in d.items() if v is not None}
    if booking_time:
        raw["booking_time"] = booking_time
    return StatementLine(
        amount=amount,
        currency=str(getattr(amount_obj, "currency", None) or d.get("currency") or "EUR"),
        booking_date=_as_date(d.get("entry_date") or d.get("guessed_entry_date")),
        value_date=_as_date(d.get("date")),
        purpose=purpose,
        counterparty_name=cp_name,
        counterparty_iban=cp_iban,
        end_to_end_id=_clean(d.get("end_to_end_reference")),
        reference=_clean(d.get("customer_reference")),
        bank_ref=_clean(d.get("bank_reference")),
        raw=raw,
    )


# -------------------------------------------------------------------- CAMT.053
def parse_camt053(data: bytes) -> list[StatementLine]:
    """CAMT.053-Auszug (XML, beliebige ``camt.053.001.xx``-Version) → Umsätze.

    Namespace-tolerant (über local-name); eine :class:`StatementLine` je ``Ntry`` mit den
    Details des ersten ``TxDtls``-Eintrags (Sammelbuchungen werden nicht aufgeteilt).

    :raises StatementParseError: kein/kaputtes CAMT-XML."""
    try:
        root = ET.fromstring(data)  # noqa: S314 - eigener Auszug, keine externen Entities
    except ET.ParseError as exc:
        raise StatementParseError(f"unparseable CAMT XML: {exc}") from exc

    entries = _findall_local(root, "Ntry")
    if not entries:
        raise StatementParseError("CAMT XML contained no entries (Ntry)")

    lines: list[StatementLine] = []
    for ntry in entries:
        amt_el = _find_local(ntry, "Amt")
        if amt_el is None or not (amt_el.text or "").strip():
            continue
        try:
            magnitude = Decimal((amt_el.text or "").strip())
        except (InvalidOperation, ValueError):
            continue
        # Richtung **explizit** verlangen: ohne klares CRDT/DBIT ist die wirtschaftliche
        # Richtung unbekannt — nicht still als Abgang annehmen (#fints-review).
        ind = (_find_text_local(ntry, "CdtDbtInd") or "").upper()
        if ind.startswith("CRDT"):
            orig_credit = True
        elif ind.startswith("DBIT"):
            orig_credit = False
        else:
            continue
        # Storno (``RvslInd=true``) kehrt die wirtschaftliche Richtung um (Rückbuchung).
        reversal = (_find_text_local(ntry, "RvslInd") or "").strip().lower() in ("true", "1")
        credit = (not orig_credit) if reversal else orig_credit
        # CAMT ``<Amt>`` ist spec-gemäß ≥ 0; ein negativer Wert würde das Vorzeichen unten
        # erneut kippen → defensiv den Betrag entkoppeln (Richtung kommt nur aus dem Indikator).
        amount = _sane_amount(abs(magnitude) if credit else -abs(magnitude))

        tx = _find_local(ntry, "TxDtls")
        scope = tx if tx is not None else ntry
        # Gegenpartei folgt dem **ursprünglichen** Indikator (Dbtr/Cdtr stehen im XML zur
        # Originalrichtung) — bei Gutschrift der Debitor (Zahler), sonst der Kreditor.
        party_tag, acct_tag = ("Dbtr", "DbtrAcct") if orig_credit else ("Cdtr", "CdtrAcct")
        party = _find_local(scope, party_tag)
        acct = _find_local(scope, acct_tag)
        cp_name, cp_iban = split_leading_iban(
            _find_text_local(party, "Nm") if party is not None else None,
            _find_text_local(acct, "IBAN") if acct is not None else None,
        )
        purpose, booking_time = _split_booking_time(_clean(_find_text_local(scope, "Ustrd")))
        lines.append(
            StatementLine(
                amount=amount,
                currency=(amt_el.get("Ccy") or "EUR").upper(),
                booking_date=_camt_date(_find_local(ntry, "BookgDt")),
                value_date=_camt_date(_find_local(ntry, "ValDt")),
                purpose=purpose,
                counterparty_name=cp_name,
                counterparty_iban=cp_iban,
                end_to_end_id=_clean(_skip_notprovided(_find_text_local(scope, "EndToEndId"))),
                reference=_clean(_find_text_local(scope, "InstrId")),
                bank_ref=_clean(_find_text_local(ntry, "AcctSvcrRef")),
                raw={
                    "creditDebit": "CRDT" if orig_credit else "DBIT",
                    **({"reversal": "true"} if reversal else {}),
                    **({"booking_time": booking_time} if booking_time else {}),
                },
            )
        )
    if not lines:
        raise StatementParseError("CAMT XML contained no usable entries")
    return lines


def parse_statement(data: bytes, *, filename: str | None = None) -> list[StatementLine]:
    """Auszug parsen — Format aus Inhalt (XML vs. nicht-XML) bzw. Endung erraten.

    :raises StatementParseError: keine der beiden Quellen passt."""
    if not data:
        raise StatementParseError("empty file")
    head = data.lstrip()[:512]
    looks_xml = head.startswith(b"<?xml") or head.startswith(b"<") and b"Document" in data[:4096]
    name = (filename or "").lower()
    if looks_xml or name.endswith(".xml"):
        return parse_camt053(data)
    return parse_mt940(data)


# ------------------------------------------------------------------ idempotency
def assign_keys(account_scope: str, lines: list[StatementLine]) -> None:
    """Idempotenz-Schlüssel je Umsatz **in-place** setzen (#fints-research).

    Bevorzugt die bank-vergebene Referenz (``bank_ref``); fehlt sie, ein Inhalts-Hash aus
    (Konto-Scope, **Wertstellung**, Cent-Betrag, Gegen-IBAN, End-to-End-Ref, gekürzter
    Zweck) **plus** einem Intraday-Lauf-Index. Der Lauf-Index trennt zwei *innerhalb eines
    Imports* identische Umsätze; die E2E-Ref trennt genuin verschiedene Zahlungen aus
    *getrennten* Importen. ``booking_date`` ist **bewusst nicht** Teil des Hashes — es ist
    bei vorgemerkten Umsätzen erst null und später gesetzt; sonst gälte derselbe Umsatz
    pending vs. gebucht als zwei verschiedene und würde doppelt importiert.
    """
    seen: dict[tuple[object, ...], int] = {}
    for ln in lines:
        if ln.bank_ref:
            ln.idempotency_key = _sha(f"{account_scope}|ref|{ln.bank_ref}")
            continue
        base: tuple[object, ...] = (
            ln.value_date.isoformat() if ln.value_date else "",
            str(ln.amount),
            ln.counterparty_iban or "",
            ln.end_to_end_id or "",
            (ln.purpose or "")[:140],
        )
        seq = seen.get(base, 0)
        seen[base] = seq + 1
        ln.idempotency_key = _sha(f"{account_scope}|{'|'.join(map(str, base))}|{seq}")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------- helpers
def _decode(data: bytes) -> str:
    # UTF-8 zuerst; latin-1 als Fallback dekodiert **jedes** Byte (kein weiterer Zweig nötig).
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _clean(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _skip_notprovided(value: str | None) -> str | None:
    """``NOTPROVIDED`` (SEPA-Platzhalter) wie leer behandeln."""
    if value and value.strip().upper() == "NOTPROVIDED":
        return None
    return value


# Manche Bank-MT940/CAMT-Felder packen Gegen-IBAN + Name OHNE Trenner in EIN Feld
# ("DE70…808Quentin Walz") und lassen das IBAN-Feld leer. Eine IBAN ist Ländercode (2
# Buchstaben) + 2 Prüfziffern + **alphanumerische** BBAN — bei NL/GB/… enthält die BBAN
# Buchstaben (z. B. ``NL70CITI2032329018``), daher reicht „nur Ziffern" NICHT (#fints). Statt
# über die Zeichenklasse zu raten, wo die IBAN endet, nutzen wir die **feste Länge je Land**
# (ISO 13616) plus die mod-97-Prüfsumme — so wird der Name nicht angeknabbert und ein bloßer
# Verwendungszweck/Referenz ("RF…") nicht fälschlich als IBAN erkannt.
_IBAN_LENGTHS = {
    "AD": 24, "AT": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24, "DE": 22,
    "DK": 18, "EE": 20, "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GR": 27, "HR": 21,
    "HU": 28, "IE": 22, "IS": 26, "IT": 27, "LI": 21, "LT": 20, "LU": 20, "LV": 21,
    "MC": 27, "MT": 31, "NL": 18, "NO": 15, "PL": 28, "PT": 25, "RO": 24, "SE": 24,
    "SI": 19, "SK": 24, "SM": 27,
}
# Führender IBAN-Kandidat: Ländercode + 2 Prüfziffern + BBAN (Großbuchstaben/Ziffern, ohne
# Leerzeichen — Bank-Glue-Felder trennen IBAN und Name nie durch ein Space).
_IBAN_HEAD = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]+")
# Sparkassen-Zusatz am Zweck-Ende: „… DATUM 03.04.2026, 09.15 UHR" (Uhrzeit mit . oder :).
_DATUM_SUFFIX = re.compile(
    r"\s*DATUM\s+\d{2}\.\d{2}\.\d{4},?\s+(\d{2})[.:](\d{2})\s*UHR\s*$",
    re.IGNORECASE,
)


def _iban_mod97_ok(iban: str) -> bool:
    """ISO 13616 mod-97-Prüfung: die ersten 4 Zeichen ans Ende, Buchstaben → Zahl (A=10…Z=35),
    Rest mod 97 muss 1 sein."""
    rearranged = iban[4:] + iban[:4]
    try:
        digits = "".join(str(int(ch, 36)) for ch in rearranged)
    except ValueError:
        return False
    return int(digits) % 97 == 1


def _detect_leading_iban(text: str) -> tuple[str, str] | None:
    """``text`` mit führender (an den Namen geklebter) IBAN → ``(iban, rest)`` oder ``None``.

    Schneidet exakt die für das Land erwartete IBAN-Länge ab und validiert die Prüfsumme —
    nur dann wird gesplittet (sonst bliebe der Name unangetastet)."""
    match = _IBAN_HEAD.match(text)
    if match is None:
        return None
    length = _IBAN_LENGTHS.get(text[:2])
    if length is None or len(match.group(0)) < length:
        return None
    candidate = text[:length]
    if not _iban_mod97_ok(candidate):
        return None
    return candidate, text[length:]


def _mt940_counterparty(
    d: dict[str, object], *, credit: bool
) -> tuple[str | None, str | None]:
    """Gegenkonto (Name, IBAN) aus einer ``mt940``-Transaktion gewinnen (#fints).

    Die ``mt940``-Lib füllt für SEPA-Umsätze außer dem strukturierten ``?32`` (``applicant_name``)
    und ``?31`` (``applicant_iban``) auch die GVC-Felder aus dem Verwendungszweck:
    ``IBAN+`` → ``gvc_applicant_iban``, ``ABWA+`` (abweichender Auftraggeber) →
    ``deviate_applicant``, ``ABWE+`` (abweichender Empfänger) → ``deviate_recipient``.

    Gerade **Gehalts-/SEPA-Zahlungen** tragen im ``?32`` oft nur ein Kürzel (z. B. „KRZL") und
    KEINE ``?31``-IBAN — der echte Gegenpart steht dann in ``ABWE+``/``ABWA+`` und die IBAN in
    ``IBAN+``. Daher: bei Eingang den abweichenden **Auftraggeber**, bei Ausgang den abweichenden
    **Empfänger** bevorzugen (sonst der jeweils andere, sonst ``?32``); die IBAN aus ``?31``,
    sonst aus ``IBAN+``. ``split_leading_iban`` trennt eine ggf. im Namen verschmolzene IBAN ab.
    """
    iban = _clean(d.get("applicant_iban")) or _clean(d.get("gvc_applicant_iban"))
    deviate_primary = "deviate_applicant" if credit else "deviate_recipient"
    deviate_secondary = "deviate_recipient" if credit else "deviate_applicant"
    name = (
        _clean(d.get(deviate_primary))
        or _clean(d.get(deviate_secondary))
        or _clean(d.get("applicant_name"))
        or _clean(d.get("recipient_name"))
    )
    return split_leading_iban(name, iban)


def split_leading_iban(
    name: object | None, iban: object | None
) -> tuple[str | None, str | None]:
    """``(name, iban)`` normalisieren: führende/wiederholte IBAN aus dem Namen lösen.

    Verbessert sowohl die Anzeige (Name + IBAN getrennt) als auch den IBAN-Abgleich (sonst
    bleibt ``counterparty_iban`` leer und das Matching greift nicht)."""
    clean_name = _clean(name)
    clean_iban = _clean(iban)
    if clean_name is None:
        return None, clean_iban
    if clean_iban and clean_name.startswith(clean_iban):
        return _clean(clean_name[len(clean_iban) :]), clean_iban
    if clean_iban is None:
        detected = _detect_leading_iban(clean_name)
        if detected:
            return _clean(detected[1]), detected[0]
    return clean_name, clean_iban


def _split_booking_time(purpose: str | None) -> tuple[str | None, str | None]:
    """Sparkassen-Suffix „… DATUM dd.mm.yyyy, hh.mm UHR" vom Zweck lösen.

    Liefert ``(sauberer_zweck, "HH:MM")`` — die Uhrzeit speist die ``Buchung:``-Zeile der
    Buchungs-Anmerkung; CAMT/andere Banken ohne diesen Zusatz → ``(zweck, None)``."""
    if not purpose:
        return purpose, None
    match = _DATUM_SUFFIX.search(purpose)
    if match is None:
        return purpose, None
    clean = purpose[: match.start()].rstrip(" -–—,")
    return (clean or None), f"{match.group(1)}:{match.group(2)}"


def format_iban(iban: str | None) -> str | None:
    """IBAN in Vierergruppen darstellen (``DE70 1203 0000 1076 8788 08``)."""
    if not iban:
        return iban
    compact = re.sub(r"\s+", "", iban).upper()
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def build_short_description(name: str | None, purpose: str | None) -> str:
    """Kurzform für die Buchungs-Beschreibung: ``<Zweck> – <Name>`` (Gedankenstrich).

    Fehlt der Zweck → nur Name; fehlt beides → ``Bankumsatz``. Der **volle** Zweck steht
    zusätzlich in der Anmerkung (:func:`build_booking_note`)."""
    name = _clean(name)
    purpose = _clean(purpose)
    if purpose and name:
        return f"{purpose} – {name}"
    return purpose or name or "Bankumsatz"


def build_booking_note(
    *,
    name: str | None,
    iban: str | None,
    purpose: str | None,
    kind: str,
    when: date | None,
    booking_time: str | None = None,
) -> str | None:
    """Strukturierte Anmerkung (Empfänger/Absender · IBAN · Zweck · Buchung) für eine Buchung
    aus einem Kontoumsatz — gleiches Format wie die kuratierten Bestandsbuchungen (#fints)."""
    name = _clean(name)
    purpose = _clean(purpose)
    rows: list[str] = []
    if name:
        rows.append(f"{'Absender' if kind == 'income' else 'Empfänger'}: {name}")
    formatted_iban = format_iban(iban)
    if formatted_iban:
        rows.append(f"IBAN: {formatted_iban}")
    if purpose:
        rows.append(f"Zweck: {purpose}")
    if when:
        stamp = f"{when.day:02d}.{when.month:02d}.{when.year}"
        if booking_time:
            stamp = f"{stamp}, {booking_time} Uhr"
        rows.append(f"Buchung: {stamp}")
    return "\n".join(rows) or None


def _as_date(value: object | None) -> date | None:
    """mt940-``Date`` (``datetime.date``-Subklasse) defensiv → ``date``."""
    if value is None:
        return None
    if isinstance(value, date):
        return date(value.year, value.month, value.day)
    return None


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
