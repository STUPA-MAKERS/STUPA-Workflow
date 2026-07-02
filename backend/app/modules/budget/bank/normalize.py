"""Reine Text-/IBAN-/Gegenkonto-Normalisierung für Kontoumsätze (#fints).

Alles hier ist frei von I/O und quellen-agnostisch einsetzbar: Zweck entkleben,
Sparkassen-Zeitstempel lösen, IBAN aus verschmolzenen Namensfeldern trennen,
Platzhalter-Gegenkonten verwerfen und Anzeige-/Buchungstexte bauen.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date


def clean(value: object | None) -> str | None:
    """``str(value).strip()`` — leere Ergebnisse und ``None`` → ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def skip_notprovided(value: str | None) -> str | None:
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
}  # fmt: skip
# Führender IBAN-Kandidat: Ländercode + 2 Prüfziffern + BBAN (Großbuchstaben/Ziffern, ohne
# Leerzeichen — Bank-Glue-Felder trennen IBAN und Name nie durch ein Space).
_IBAN_HEAD = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]+")
# Sparkassen-Zusatz am Zweck-Ende: „… DATUM 03.04.2026, 09.15 UHR" (Uhrzeit mit . oder :).
_DATUM_SUFFIX = re.compile(
    r"\s*DATUM\s+\d{2}\.\d{2}\.\d{4},?\s+(\d{2})[.:](\d{2})\s*UHR\s*$",
    re.IGNORECASE,
)

# Strukturierte ?86-Tags, die die ``mt940``-Lib bei manchen Banken OHNE Trenner an den
# vorigen Zweck-Teil klebt (z. B. „…0000794247ANZAHL 00000002") → Leerzeichen davor einfügen.
_GLUE_TOKENS = (
    "DATEI-NR.",
    "ANZAHL",
    "DATUM",
    "EREF+",
    "KREF+",
    "MREF+",
    "CRED+",
    "DEBT+",
    "SVWZ+",
    "ABWA+",
    "ABWE+",
    "IBAN+",
    "BIC+",
)
_GLUE_RE = re.compile(r"(?<=\S)(" + "|".join(re.escape(t) for t in _GLUE_TOKENS) + r")")
# Datum direkt an ein folgendes Wort geklebt: „30.06.2026siehe" → „30.06.2026 siehe".
_DATE_GLUE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})(?=[A-Za-zÄÖÜäöü])")
# Platzhalter-„Namen", die manche Sparkassen im ?32 statt eines echten Gegenkontos liefern
# (Sammel-/Dateibuchungen) — nicht als Gegenkonto anzeigen.
_PLACEHOLDER_NAMES = frozenset({"KRZL"})

# Sparkassen-Sammel-/Dateibuchung: der Zweck besteht nur aus Datei-Nummer + Posten-Zahl
# („DATEI-NR. 0000794247 ANZAHL 00000002"). Für die Anzeige menschenlesbar machen —
# gespeicherte/rohe Zwecke bleiben unverändert (Dedup fußt auf den Rohdaten, #fints-raw).
_BATCH_PURPOSE_RE = re.compile(
    r"DATEI-NR\.?\s*0*(\d+)\s+ANZAHL\s+0*(\d+)",
    re.IGNORECASE,
)


def normalize_purpose(text: str | None) -> str | None:
    """Verklebte ?86-Subfelder wieder trennen (#fints): Leerzeichen vor strukturierte Tags und
    zwischen Datum + Folgewort, Mehrfach-Leerzeichen kollabieren. Reine Darstellungs-/Lesbarkeit;
    der :func:`split_booking_time`-Schritt entfernt danach den ``DATUM …UHR``-Zusatz."""
    if not text:
        return text
    text = _GLUE_RE.sub(r" \1", text)
    text = _DATE_GLUE_RE.sub(r"\1 ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text or None


def prettify_purpose(text: str | None) -> str | None:
    """Sparkassen-Sammelbuchungszweck menschenlesbar machen (Anzeige, #fints-batch).

    „DATEI-NR. 0000794247 ANZAHL 00000002" → „Sammelbuchung Datei-Nr. 794247 (2 Posten)";
    umgebender Text bleibt erhalten. Zwecke ohne das Muster kommen unverändert zurück."""
    if not text:
        return text

    def _pretty(match: re.Match[str]) -> str:
        count = int(match.group(2))
        posten = "1 Posten" if count == 1 else f"{count} Posten"
        return f"Sammelbuchung Datei-Nr. {int(match.group(1))} ({posten})"

    return _BATCH_PURPOSE_RE.sub(_pretty, text)


def split_booking_time(purpose: str | None) -> tuple[str | None, str | None]:
    """Sparkassen-Suffix „… DATUM dd.mm.yyyy, hh.mm UHR" vom Zweck lösen.

    Liefert ``(sauberer_zweck, "HH:MM")`` — die Uhrzeit speist die ``Buchung:``-Zeile der
    Buchungs-Anmerkung; CAMT/andere Banken ohne diesen Zusatz → ``(zweck, None)``."""
    if not purpose:
        return purpose, None
    match = _DATUM_SUFFIX.search(purpose)
    if match is None:
        return purpose, None
    clean_text = purpose[: match.start()].rstrip(" -–—,")
    return (clean_text or None), f"{match.group(1)}:{match.group(2)}"


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


def split_leading_iban(
    name: object | None, iban: object | None
) -> tuple[str | None, str | None]:
    """``(name, iban)`` normalisieren: führende/wiederholte IBAN aus dem Namen lösen.

    Verbessert sowohl die Anzeige (Name + IBAN getrennt) als auch den IBAN-Abgleich (sonst
    bleibt ``counterparty_iban`` leer und das Matching greift nicht)."""
    clean_name = clean(name)
    clean_iban = clean(iban)
    if clean_name is None:
        return None, clean_iban
    if clean_iban and clean_name.startswith(clean_iban):
        return clean(clean_name[len(clean_iban) :]), clean_iban
    if clean_iban is None:
        detected = _detect_leading_iban(clean_name)
        if detected:
            return clean(detected[1]), detected[0]
    return clean_name, clean_iban


def clean_counterparty_name(name: object | None) -> str | None:
    """Platzhalter-„Namen" (z. B. „KRZL" bei Sammel-/Dateibuchungen) verwerfen — egal aus welcher
    Quelle (#fints-raw). Greift auch im Fallback auf die gespeicherte Spalte, falls die Rohfelder
    den echten Namen nicht hergeben."""
    cleaned = clean(name)
    if cleaned is not None and cleaned.upper() in _PLACEHOLDER_NAMES:
        return None
    return cleaned


def mt940_counterparty(
    d: Mapping[str, object], *, credit: bool
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
    sonst aus ``IBAN+``. :func:`split_leading_iban` trennt eine ggf. im Namen verschmolzene IBAN ab.
    """
    iban = clean(d.get("applicant_iban")) or clean(d.get("gvc_applicant_iban"))
    deviate_primary = "deviate_applicant" if credit else "deviate_recipient"
    deviate_secondary = "deviate_recipient" if credit else "deviate_applicant"
    name = (
        clean(d.get(deviate_primary))
        or clean(d.get(deviate_secondary))
        or clean(d.get("applicant_name"))
        or clean(d.get("recipient_name"))
    )
    # ERST die ggf. verschmolzene IBAN abtrennen, DANN Platzhalter prüfen: Sammelbuchungen liefern
    # ``applicant_name`` als „<IBAN>KRZL" (IBAN + Kürzel zusammengeklebt, keine eigene ?31-IBAN).
    # Ein Check VOR dem Split würde „<IBAN>KRZL" nicht als Platzhalter erkennen und „KRZL" stehen
    # lassen (#fints-raw).
    clean_name, clean_iban = split_leading_iban(name, iban)
    if clean_name is not None and clean_name.upper() in _PLACEHOLDER_NAMES:
        clean_name = None
    return clean_name, clean_iban


def resolve_counterparty(raw: object, *, credit: bool) -> tuple[str | None, str | None]:
    """Gegenkonto **aus den Rohdaten** auflösen (#fints-raw). MT940/FinTS: über die GVC-Rohfelder
    (:func:`mt940_counterparty`, verwirft Platzhalter wie ``KRZL``, löst geklebte IBAN). CAMT-Roh
    trägt diese Felder nicht → ``(None, None)`` (Aufrufer nutzt dann die gespeicherte Spalte)."""
    if not isinstance(raw, dict):
        return None, None
    return mt940_counterparty(raw, credit=credit)


def resolve_purpose(raw: object) -> str | None:
    """Verwendungszweck **aus den Rohdaten** auflösen (#fints-raw): Roh-``purpose`` entkleben +
    ``DATUM…UHR`` lösen. Roh ohne ``purpose`` → ``None`` (Aufrufer nutzt die Spalte)."""
    if not isinstance(raw, dict) or raw.get("purpose") is None:
        return None
    return split_booking_time(normalize_purpose(clean(raw.get("purpose"))))[0]


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
    name = clean(name)
    purpose = prettify_purpose(clean(purpose))
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
    name = clean(name)
    purpose = prettify_purpose(clean(purpose))
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
