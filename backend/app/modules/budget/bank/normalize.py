"""Pure text, IBAN and counterparty normalization for statement lines.

The functions here do no I/O and do not depend on the source format. They unglue
purposes, detach Sparkasse timestamps, split IBANs out of merged name fields,
drop placeholder counterparties and build the display and booking texts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date


def clean(value: object | None) -> str | None:
    """Return ``str(value).strip()``.

    An empty result and ``None`` both become ``None``.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def skip_notprovided(value: str | None) -> str | None:
    """Treat ``NOTPROVIDED`` (SEPA placeholder) as empty."""
    if value and value.strip().upper() == "NOTPROVIDED":
        return None
    return value


# Some bank MT940/CAMT fields pack the counterparty IBAN and name into ONE field
# WITHOUT a separator ("DE70…808Quentin Walz") and leave the IBAN field empty. A
# BBAN holds letters and digits, for example ``NL70CITI2032329018``. "Digits only"
# is therefore not enough to find the boundary. Use the fixed per-country length
# of ISO 13616 plus the mod-97 checksum instead. That keeps the name intact and
# stops a plain reference ("RF…") from passing as an IBAN.
_IBAN_LENGTHS = {
    "AD": 24, "AT": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24, "DE": 22,
    "DK": 18, "EE": 20, "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GR": 27, "HR": 21,
    "HU": 28, "IE": 22, "IS": 26, "IT": 27, "LI": 21, "LT": 20, "LU": 20, "LV": 21,
    "MC": 27, "MT": 31, "NL": 18, "NO": 15, "PL": 28, "PT": 25, "RO": 24, "SE": 24,
    "SI": 19, "SK": 24, "SM": 27,
}  # fmt: skip
# Leading IBAN candidate: country code, 2 check digits and the BBAN in uppercase
# characters and digits. No spaces: a bank glue field never separates IBAN and
# name with a space.
_IBAN_HEAD = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]+")
# Sparkasse suffix at the purpose end: "… DATUM 03.04.2026, 09.15 UHR" (time with . or :).
_DATUM_SUFFIX = re.compile(
    r"\s*DATUM\s+\d{2}\.\d{2}\.\d{4},?\s+(\d{2})[.:](\d{2})\s*UHR\s*$",
    re.IGNORECASE,
)

# Structured ?86 tags that the ``mt940`` lib glues to the preceding purpose part
# at some banks, for example "…0000794247ANZAHL 00000002". Insert a space before
# each tag.
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
# Date glued directly to a following word: "30.06.2026siehe" -> "30.06.2026 siehe".
_DATE_GLUE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})(?=[A-Za-zÄÖÜäöü])")
# Placeholder "names" that some Sparkassen put in ?32 instead of a real
# counterparty on batch and file bookings. Do not show these as a counterparty.
_PLACEHOLDER_NAMES = frozenset({"KRZL"})

# Sparkasse batch and file booking: the purpose holds only the file number and the
# item count ("DATEI-NR. 0000794247 ANZAHL 00000002"). The code prettifies it for
# the display only. The stored and raw purposes stay unchanged, because the dedup
# rests on the raw data.
_BATCH_PURPOSE_RE = re.compile(
    r"DATEI-NR\.?\s*0*(\d+)\s+ANZAHL\s+0*(\d+)",
    re.IGNORECASE,
)


def normalize_purpose(text: str | None) -> str | None:
    """Re-separate the glued ?86 subfields of a purpose.

    The function inserts a space before a structured tag and between a date and
    the word that follows. It also collapses repeated spaces. The change serves
    the display only. ``split_booking_time`` removes the ``DATUM …UHR`` suffix
    after this step.
    """
    if not text:
        return text
    text = _GLUE_RE.sub(r" \1", text)
    text = _DATE_GLUE_RE.sub(r"\1 ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text or None


def prettify_purpose(text: str | None) -> str | None:
    """Make a Sparkasse batch-booking purpose readable for a person (display only).

    "DATEI-NR. 0000794247 ANZAHL 00000002" becomes "Sammelbuchung Datei-Nr.
    794247 (2 Posten)". The function keeps the surrounding text. A purpose without
    the pattern passes through unchanged.
    """
    if not text:
        return text

    def _pretty(match: re.Match[str]) -> str:
        count = int(match.group(2))
        posten = "1 Posten" if count == 1 else f"{count} Posten"
        return f"Sammelbuchung Datei-Nr. {int(match.group(1))} ({posten})"

    return _BATCH_PURPOSE_RE.sub(_pretty, text)


def split_booking_time(purpose: str | None) -> tuple[str | None, str | None]:
    """Detach the Sparkasse suffix "… DATUM dd.mm.yyyy, hh.mm UHR" from the purpose.

    The time feeds the ``Buchung:`` row of the booking note. A CAMT statement or
    another bank without the suffix yields ``(purpose, None)``.

    Returns:
        The clean purpose and the time as ``"HH:MM"``.
    """
    if not purpose:
        return purpose, None
    match = _DATUM_SUFFIX.search(purpose)
    if match is None:
        return purpose, None
    clean_text = purpose[: match.start()].rstrip(" -–—,")
    return (clean_text or None), f"{match.group(1)}:{match.group(2)}"


def _iban_mod97_ok(iban: str) -> bool:
    """Run the ISO 13616 mod-97 check on an IBAN.

    The check moves the first 4 characters to the end and maps the letters
    A=10…Z=35. The remainder modulo 97 must be 1.
    """
    rearranged = iban[4:] + iban[:4]
    try:
        digits = "".join(str(int(ch, 36)) for ch in rearranged)
    except ValueError:
        return False
    return int(digits) % 97 == 1


def _detect_leading_iban(text: str) -> tuple[str, str] | None:
    """Split ``text`` with a leading name-glued IBAN into ``(iban, rest)``.

    The function cuts exactly the IBAN length that the country expects and checks
    the checksum. Only then does it apply the split. Otherwise the name stays
    untouched.

    Returns:
        The IBAN and the rest of the text, or ``None`` when ``text`` carries no
        leading IBAN.
    """
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
    """Normalize ``(name, iban)`` and detach a leading or repeated IBAN from the name.

    This helps the display, because name and IBAN stay separate. It also helps the
    IBAN matching. Without the split, ``counterparty_iban`` stays empty and the
    matching never fires.
    """
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
    """Drop placeholder "names" from any source, for example "KRZL".

    A batch or file booking carries such a placeholder. The rule also applies to
    the stored-column fallback, when the raw fields hold no real name.
    """
    cleaned = clean(name)
    if cleaned is not None and cleaned.upper() in _PLACEHOLDER_NAMES:
        return None
    return cleaned


def mt940_counterparty(
    d: Mapping[str, object], *, credit: bool
) -> tuple[str | None, str | None]:
    """Extract the counterparty name and IBAN from an ``mt940`` transaction.

    Besides the structured ``?32`` (``applicant_name``) and ``?31``
    (``applicant_iban``), the lib fills GVC fields from the purpose: ``IBAN+`` ->
    ``gvc_applicant_iban``, ``ABWA+`` -> ``deviate_applicant``, ``ABWE+`` ->
    ``deviate_recipient``. A salary or SEPA payment often carries only a
    placeholder in ``?32`` and no ``?31`` IBAN. The real counterparty then sits in
    ``ABWE+`` or ``ABWA+``, and the IBAN in ``IBAN+``. On income the function
    prefers the deviating originator. On outflow it prefers the deviating
    recipient. It then falls back to the other field and finally to ``?32``. It
    takes the IBAN from ``?31``, else from ``IBAN+``. ``split_leading_iban``
    detaches a name-glued IBAN.
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
    # Detach the glued IBAN FIRST, THEN check the placeholders. A batch booking
    # delivers ``applicant_name`` as "<IBAN>KRZL" without a separate ?31 IBAN. A
    # check before the split would not see "<IBAN>KRZL" as a placeholder and would
    # leave "KRZL" in place.
    clean_name, clean_iban = split_leading_iban(name, iban)
    if clean_name is not None and clean_name.upper() in _PLACEHOLDER_NAMES:
        clean_name = None
    return clean_name, clean_iban


def resolve_counterparty(raw: object, *, credit: bool) -> tuple[str | None, str | None]:
    """Resolve the counterparty from the raw data.

    MT940 and FinTS use the GVC raw fields through ``mt940_counterparty``. CAMT
    raw data holds no such fields and yields ``(None, None)``. The caller then
    uses the stored column.
    """
    if not isinstance(raw, dict):
        return None, None
    return mt940_counterparty(raw, credit=credit)


def resolve_purpose(raw: object) -> str | None:
    """Resolve the purpose from the raw data.

    The function unglues the raw ``purpose`` and detaches ``DATUM…UHR``. Raw data
    without a ``purpose`` yields ``None``, and the caller then uses the column.
    """
    if not isinstance(raw, dict) or raw.get("purpose") is None:
        return None
    return split_booking_time(normalize_purpose(clean(raw.get("purpose"))))[0]


def format_iban(iban: str | None) -> str | None:
    """Format an IBAN in groups of four (``DE70 1203 0000 1076 8788 08``)."""
    if not iban:
        return iban
    compact = re.sub(r"\s+", "", iban).upper()
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def build_short_description(name: str | None, purpose: str | None) -> str:
    """Build the short booking description ``<purpose> – <name>`` with an en dash.

    Without a purpose the result holds the name only. Without both the result is
    ``Bankumsatz``. The note also carries the full purpose (``build_booking_note``).
    """
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
    """Build the structured note for a booking that comes from a statement line.

    The note holds recipient or sender, IBAN, purpose and booking. The format
    matches the curated existing bookings.
    """
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
