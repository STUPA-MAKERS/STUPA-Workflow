"""Kontoauszug-Parser (#fints): MT940 + CAMT.053 + Idempotenz. Reine Unit-Tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.budget import bank_import as bi

_MT940 = b""":20:STARTUMS
:25:12345678/1234567890
:28C:00000/001
:60F:C240101EUR1000,00
:61:2401020102DR50,00NTRFNONREF//POS 1
:86:166?00UEBERWEISUNG?20Miete Mai?21Rechnung 42?32MUSTERMANN GMBH?38DE89370400440532013000
:61:2401030103CR200,00NTRFNONREF//POS 2
:86:051?00GUTSCHRIFT?20Mitgliedsbeitrag?32ERIKA?38DE12500105170648489890
:62F:C240103EUR1150,00
-"""

_CAMT = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
 <BkToCstmrStmt><Stmt>
  <Ntry>
   <Amt Ccy="EUR">50.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>
   <BookgDt><Dt>2024-01-02</Dt></BookgDt><ValDt><Dt>2024-01-02</Dt></ValDt>
   <AcctSvcrRef>BANKREF001</AcctSvcrRef>
   <NtryDtls><TxDtls>
     <Refs><EndToEndId>NOTPROVIDED</EndToEndId></Refs>
     <RltdPties><Cdtr><Nm>MUSTERMANN GMBH</Nm></Cdtr>
       <CdtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></CdtrAcct></RltdPties>
     <RmtInf><Ustrd>Miete Mai</Ustrd></RmtInf>
   </TxDtls></NtryDtls>
  </Ntry>
  <Ntry>
   <Amt Ccy="EUR">200.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
   <BookgDt><Dt>2024-01-03</Dt></BookgDt><ValDt><Dt>2024-01-03</Dt></ValDt>
   <AcctSvcrRef>BANKREF002</AcctSvcrRef>
   <NtryDtls><TxDtls>
     <Refs><EndToEndId>E2E-7788</EndToEndId></Refs>
     <RltdPties><Dbtr><Nm>ERIKA MUSTERFRAU</Nm></Dbtr>
       <DbtrAcct><Id><IBAN>DE12500105170648489890</IBAN></Id></DbtrAcct></RltdPties>
     <RmtInf><Ustrd>Mitgliedsbeitrag 2024</Ustrd></RmtInf>
   </TxDtls></NtryDtls>
  </Ntry>
 </Stmt></BkToCstmrStmt>
</Document>"""


def test_parse_mt940_signs_and_fields() -> None:
    lines = bi.parse_mt940(_MT940)
    assert len(lines) == 2
    debit, credit = lines
    assert debit.amount == Decimal("-50.00")  # Soll → negativ
    assert credit.amount == Decimal("200.00")  # Haben → positiv
    assert debit.value_date == date(2024, 1, 2)
    assert "Miete Mai" in (debit.purpose or "")
    assert debit.counterparty_name == "MUSTERMANN GMBH"


def test_parse_camt_credit_debit_counterparty_and_notprovided() -> None:
    lines = bi.parse_camt053(_CAMT)
    assert len(lines) == 2
    debit, credit = lines
    assert debit.amount == Decimal("-50.00")
    assert debit.counterparty_iban == "DE89370400440532013000"
    assert debit.end_to_end_id is None  # NOTPROVIDED → leer
    assert credit.amount == Decimal("200.00")
    assert credit.counterparty_name == "ERIKA MUSTERFRAU"
    assert credit.end_to_end_id == "E2E-7788"
    assert credit.bank_ref == "BANKREF002"


def test_parse_statement_dispatch() -> None:
    assert len(bi.parse_statement(_CAMT, filename="x.xml")) == 2
    assert len(bi.parse_statement(_MT940, filename="x.sta")) == 2
    # XML ohne Endung wird am Inhalt erkannt.
    assert len(bi.parse_statement(_CAMT)) == 2


def test_parse_errors() -> None:
    with pytest.raises(bi.StatementParseError):
        bi.parse_statement(b"")
    with pytest.raises(bi.StatementParseError):
        bi.parse_camt053(b"<Document></Document>")
    with pytest.raises(bi.StatementParseError):
        bi.parse_camt053(b"<<<not xml")
    with pytest.raises(bi.StatementParseError):
        bi.parse_mt940(b"garbage without tags")


def test_assign_keys_uses_bank_ref_when_present() -> None:
    lines = bi.parse_camt053(_CAMT)
    bi.assign_keys("DE-ACCT", lines)
    assert all(line.idempotency_key for line in lines)
    # Re-Parse + Re-Key → gleiche Schlüssel (idempotent).
    again = bi.parse_camt053(_CAMT)
    bi.assign_keys("DE-ACCT", again)
    assert [line.idempotency_key for line in lines] == [line.idempotency_key for line in again]


def test_assign_keys_disambiguates_identical_lines_without_ref() -> None:
    a = bi.StatementLine(amount=Decimal("-5.00"), value_date=date(2024, 5, 1), purpose="Kaffee")
    b = bi.StatementLine(amount=Decimal("-5.00"), value_date=date(2024, 5, 1), purpose="Kaffee")
    bi.assign_keys("scope", [a, b])
    assert a.idempotency_key != b.idempotency_key  # Intraday-Sequenz trennt Dubletten


def test_amount_out_of_range_rejected() -> None:
    huge = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt><Ntry>
 <Amt Ccy="EUR">99999999999.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
</Ntry></Stmt></Document>"""
    with pytest.raises(bi.StatementParseError):
        bi.parse_camt053(huge)


# --------------------------------------------------- review round 4 (#fints-review)
class _Amt:
    def __init__(self, amount: str, currency: str = "EUR") -> None:
        self.amount = Decimal(amount)
        self.currency = currency


class _Tx:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data


def test_mt940_sign_from_status() -> None:
    """Vorzeichen explizit aus dem Status — inkl. Storno-Marker RC/RD (#fints-review)."""
    def amt(status: str, value: str = "50.00") -> Decimal:
        return bi.lines_from_mt940_transactions(
            [_Tx({"amount": _Amt(value), "status": status})]
        )[0].amount

    assert amt("D") == Decimal("-50.00")
    assert amt("C") == Decimal("50.00")
    # RC = Storno einer Gutschrift = Abgang → negativ (der eigentliche Bug-Fix).
    assert amt("RC") == Decimal("-50.00")
    # RD = Storno einer Lastschrift = Eingang → positiv.
    assert amt("RD") == Decimal("50.00")
    # Unbekannter/leerer Status → Vorzeichen der Lib beibehalten (hier negativ vorgegeben).
    neg = bi.lines_from_mt940_transactions([_Tx({"amount": _Amt("-7.00")})])[0]
    assert neg.amount == Decimal("-7.00")


def test_camt_direction_edges() -> None:
    """Fehlender Indikator → übersprungen; RvslInd kehrt um; negativer <Amt> → abs."""
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt>
 <Ntry><Amt Ccy="EUR">10.00</Amt></Ntry>
 <Ntry><Amt Ccy="EUR">20.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><RvslInd>true</RvslInd></Ntry>
 <Ntry><Amt Ccy="EUR">-30.00</Amt><CdtDbtInd>DBIT</CdtDbtInd></Ntry>
</Stmt></Document>"""
    lines = bi.parse_camt053(xml)
    assert len(lines) == 2  # erster (ohne CdtDbtInd) übersprungen
    assert lines[0].amount == Decimal("-20.00")  # Storno einer Gutschrift = Abgang
    assert lines[0].raw.get("reversal") == "true"
    assert lines[1].amount == Decimal("-30.00")  # negativer <Amt> → abs, dann DBIT


def test_parse_statement_full_mt940_balance() -> None:
    """MT940-Schlusssaldo (:62F:) wird mitgeliefert (#fints-konten)."""
    lines, bal = bi.parse_statement_full(_MT940)
    assert len(lines) == 2
    assert bal is not None
    assert bal.amount == Decimal("1150.00")
    assert bal.currency == "EUR"
    assert bal.as_of == date(2024, 1, 3)


def test_camt_closing_balance_clbd_signed() -> None:
    """CAMT-Schlusssaldo aus CLBD; Vorzeichen aus CdtDbtInd (DBIT → negativ)."""
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt>
 <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">2500.00</Amt>
  <CdtDbtInd>DBIT</CdtDbtInd><Dt><Dt>2026-06-30</Dt></Dt></Bal>
 <Ntry><Amt Ccy="EUR">50.00</Amt><CdtDbtInd>DBIT</CdtDbtInd></Ntry>
</Stmt></Document>"""
    _lines, bal = bi.parse_statement_full(xml)
    assert bal is not None
    assert bal.amount == Decimal("-2500.00")  # DBIT → Soll-Saldo
    assert bal.as_of == date(2026, 6, 30)


def test_camt_no_balance() -> None:
    """Ohne <Bal>-Element → kein Saldo (Liste trotzdem geparst)."""
    lines, bal = bi.parse_statement_full(_CAMT)
    assert len(lines) == 2
    assert bal is None


def test_balance_from_mt940_handles_missing() -> None:
    assert bi.balance_from_mt940(object()) is None  # kein .amount


def test_normalize_purpose_unglues_subfields() -> None:
    """Verklebte ?86-Subfelder werden wieder getrennt (#fints)."""
    assert bi._normalize_purpose("DATEI-NR. 0000794247ANZAHL 00000002") == (
        "DATEI-NR. 0000794247 ANZAHL 00000002"
    )
    assert bi._normalize_purpose("Abrechnung 30.06.2026siehe Anlage") == (
        "Abrechnung 30.06.2026 siehe Anlage"
    )
    assert bi._normalize_purpose(None) is None
    assert bi._normalize_purpose("   ") is None


def test_normalize_then_split_strips_datum_suffix() -> None:
    """Auch ohne Leerzeichen vor ``DATUM`` wird der Zeit-Zusatz gelöst."""
    purpose, time = bi._split_booking_time(
        bi._normalize_purpose("Asta-Aufwandsentschädigung 05/2026DATUM 09.06.2026, 15.54 UHR")
    )
    assert purpose == "Asta-Aufwandsentschädigung 05/2026"
    assert time == "15:54"


def test_canonical_purpose_key_ignores_spacing_and_punct() -> None:
    """Kanonischer Schlüssel ist gegen Leerzeichen/Interpunktion invariant (#fints-dedup)."""
    assert bi.canonical_purpose_key("DATEI-NR. 0000794247ANZAHL 00000002") == (
        bi.canonical_purpose_key("DATEI-NR. 0000794247 ANZAHL 00000002")
    )


def test_assign_keys_from_raw_stable_across_parser_versions() -> None:
    """Schlüssel kommt aus den ROHDATEN (#fints-raw): identisches ``raw`` → GLEICHER Schlüssel,
    egal wie die abgeleiteten ``purpose``/``counterparty_*`` aussehen (alte vs. neue Parser-
    Version). Sonst dupliziert ein Re-Import die bereits gebuchte Zeile."""
    raw = {"purpose": "oikos Spende", "applicant_name": "oikos Bayreuth e.V.",
           "applicant_iban": "DE85780608960006017410"}
    old = bi.StatementLine(  # alt geparst: IBAN im Namen verklebt, abweichender Zweck
        amount=Decimal("-1377.27"), value_date=date(2026, 6, 26),
        counterparty_name="DE85780608960006017410oikos Bayreuth e.V.",
        counterparty_iban=None, purpose="oikos SpendeDATUM 01.01.2026, 10.00 UHR", raw=dict(raw),
    )
    new = bi.StatementLine(  # neu geparst: sauber — aber GLEICHES raw
        amount=Decimal("-1377.27"), value_date=date(2026, 6, 26),
        counterparty_name="oikos Bayreuth e.V.",
        counterparty_iban="DE85780608960006017410", purpose="oikos Spende", raw=dict(raw),
    )
    bi.assign_keys("acc", [old])
    bi.assign_keys("acc", [new])
    assert old.idempotency_key == new.idempotency_key


def test_assign_keys_distinct_for_different_raw_counterparty() -> None:
    """Echte Einzelzahlungen (anderer Roh-Auftraggeber) → UNTERSCHIEDLICHE Schlüssel (kein
    fälschliches Zusammenfassen, #fints-raw)."""
    a = bi.StatementLine(amount=Decimal("-80.00"), value_date=date(2026, 5, 26),
                         purpose="Aufwand", raw={"purpose": "Aufwand", "applicant_name": "Alice"})
    b = bi.StatementLine(amount=Decimal("-80.00"), value_date=date(2026, 5, 26),
                         purpose="Aufwand", raw={"purpose": "Aufwand", "applicant_name": "Bob"})
    bi.assign_keys("acc", [a, b])
    assert a.idempotency_key != b.idempotency_key


def test_resolve_from_raw_helpers() -> None:
    """resolve_* arbeiten auf den Rohdaten; Nicht-Dict/fehlende Felder → Fallback-Signale."""
    # MT940-Roh → sauberes Gegenkonto (KRZL verworfen) + entklebter/ge-stripter Zweck
    name, iban = bi.resolve_counterparty(
        {"applicant_name": "KRZL", "gvc_applicant_iban": "DE79640500000100083958"}, credit=False
    )
    assert name is None and iban == "DE79640500000100083958"
    assert bi.resolve_purpose({"purpose": "Re 0000794247ANZAHL 2"}) == "Re 0000794247 ANZAHL 2"
    # CAMT-Roh / kein Dict / kein purpose → None-Signale (Aufrufer nutzt die Spalte)
    assert bi.resolve_counterparty(None, credit=True) == (None, None)
    assert bi.resolve_counterparty({"creditDebit": "CRDT"}, credit=True) == (None, None)
    assert bi.resolve_purpose(None) is None
    assert bi.resolve_purpose({"creditDebit": "CRDT"}) is None


def test_mt940_counterparty_drops_krzl_glued_to_iban() -> None:
    """Reale Sammelbuchung: ``applicant_name`` = „<IBAN>KRZL" (kein eigenes ?31). Erst IBAN lösen,
    DANN „KRZL" verwerfen → (None, IBAN), nicht „KRZL" (#fints-raw)."""
    name, iban = bi.mt940_counterparty(
        {"applicant_name": "DE79640500000100083958KRZL"}, credit=False
    )
    assert name is None
    assert iban == "DE79640500000100083958"


def test_mt940_counterparty_drops_krzl_placeholder() -> None:
    """„KRZL"-Platzhalter (Sammel-/Dateibuchung) wird nicht als Gegenkonto übernommen."""
    name, iban = bi.mt940_counterparty(
        {"applicant_name": "KRZL", "gvc_applicant_iban": "DE79640500000100083958"},
        credit=False,
    )
    assert name is None
    assert iban == "DE79640500000100083958"


def test_camt_balance_clav_fallback_and_skips_codeless() -> None:
    """Ohne CLBD → Fallback auf CLAV; <Bal> ohne Code wird übersprungen."""
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt>
 <Bal><Amt Ccy="EUR">1.00</Amt></Bal>
 <Bal><Tp><CdOrPrtry><Cd>CLAV</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">300.00</Amt>
  <CdtDbtInd>CRDT</CdtDbtInd></Bal>
 <Ntry><Amt Ccy="EUR">50.00</Amt><CdtDbtInd>DBIT</CdtDbtInd></Ntry>
</Stmt></Document>"""
    _lines, bal = bi.parse_statement_full(xml)
    assert bal is not None
    assert bal.amount == Decimal("300.00")


def test_camt_balance_unparseable_amount_ignored() -> None:
    """CLBD ohne brauchbaren Betrag → kein Saldo (Liste bleibt geparst)."""
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt>
 <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp></Bal>
 <Ntry><Amt Ccy="EUR">50.00</Amt><CdtDbtInd>DBIT</CdtDbtInd></Ntry>
</Stmt></Document>"""
    _lines, bal = bi.parse_statement_full(xml)
    assert bal is None


def test_camt_sub_cent_rejected() -> None:
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt><Ntry>
 <Amt Ccy="EUR">100.005</Amt><CdtDbtInd>CRDT</CdtDbtInd>
</Ntry></Stmt></Document>"""
    with pytest.raises(bi.StatementParseError):
        bi.parse_camt053(xml)


def test_split_leading_iban() -> None:
    """Gegen-IBAN + Name in einem Feld trennen (#fints)."""
    # IBAN-Feld leer, Name = IBAN+Name ohne Trenner → abgespalten (volle, gültige DE-IBAN).
    assert bi.split_leading_iban("DE70120300001076878808Quentin Walz", None) == (
        "Quentin Walz",
        "DE70120300001076878808",
    )
    # NL-IBAN mit Buchstaben in der BBAN (CITI) — die alte „nur Ziffern"-Heuristik scheiterte
    # hier; Längen-Tabelle + Prüfsumme trennt korrekt (#fints).
    assert bi.split_leading_iban("NL70CITI2032329018Stichting Mollie Payments", None) == (
        "Stichting Mollie Payments",
        "NL70CITI2032329018",
    )
    # Name = nur IBAN (kein Name) → Name None, IBAN gesetzt.
    assert bi.split_leading_iban("DE89370400440532013000", None) == (
        None,
        "DE89370400440532013000",
    )
    # Ungültige Prüfsumme / zu kurz → NICHT als IBAN gedeutet, Name bleibt unangetastet.
    assert bi.split_leading_iban("DE85780608960006017", None) == (
        "DE85780608960006017",
        None,
    )
    # Referenz, die nur wie eine IBAN aussieht (kein gültiger Ländercode) → kein Split.
    assert bi.split_leading_iban("RF1234567890Acme", None) == ("RF1234567890Acme", None)
    # IBAN-Feld da und im Namen wiederholt → Präfix entfernen.
    assert bi.split_leading_iban("DE111Heldenwerbung", "DE111") == (
        "Heldenwerbung",
        "DE111",
    )
    # Saubere getrennte Felder bleiben unverändert.
    assert bi.split_leading_iban("Quentin Walz", "DE70120300001076878808") == (
        "Quentin Walz",
        "DE70120300001076878808",
    )
    # Kein Name → (None, IBAN); reiner Name ohne IBAN bleibt unverändert.
    assert bi.split_leading_iban(None, "DE111") == (None, "DE111")
    assert bi.split_leading_iban("Plain Name", None) == ("Plain Name", None)


def test_mt940_counterparty_prefers_sepa_fields() -> None:
    """Gehalts-/SEPA-Umsätze: echten Gegenpart aus ABWE+/ABWA+ + IBAN+ ziehen, nicht aus dem
    Kürzel in ?32 (#fints)."""
    # Ausgang (Gehalt): ?32 nur Kürzel, ?31 leer; echter Empfänger in ABWE+, IBAN in IBAN+.
    salary = {
        "applicant_name": "KRZL",
        "applicant_iban": None,
        "deviate_recipient": "Max Mustermann",
        "gvc_applicant_iban": "DE70120300001076878808",
    }
    assert bi.mt940_counterparty(salary, credit=False) == (
        "Max Mustermann",
        "DE70120300001076878808",
    )
    # Eingang: abweichender Auftraggeber (ABWA+) wird bevorzugt.
    incoming = {"applicant_name": "KRZL", "deviate_applicant": "ACME GmbH"}
    assert bi.mt940_counterparty(incoming, credit=True) == ("ACME GmbH", None)
    # Ohne abweichende Felder: Fallback auf ?32 (+ ?31 vor IBAN+).
    plain = {
        "applicant_name": "Quentin Walz",
        "applicant_iban": "DE89370400440532013000",
        "gvc_applicant_iban": "DE111",
    }
    assert bi.mt940_counterparty(plain, credit=False) == (
        "Quentin Walz",
        "DE89370400440532013000",
    )
    # Komplett leer → (None, None).
    assert bi.mt940_counterparty({}, credit=False) == (None, None)


def test_split_booking_time() -> None:
    """Sparkassen-Suffix „… DATUM dd.mm.yyyy, hh.mm UHR" vom Zweck lösen (#fints)."""
    assert bi._split_booking_time(
        "AStA-Aufwandsentschädigung 03/26DATUM 03.04.2026, 09.15 UHR"
    ) == ("AStA-Aufwandsentschädigung 03/26", "09:15")
    # Uhrzeit mit Doppelpunkt + Kleinschreibung ebenfalls erkannt.
    assert bi._split_booking_time("Miete Mai datum 01.05.2026 08:00 uhr") == (
        "Miete Mai",
        "08:00",
    )
    # Ohne Suffix unverändert; None bleibt None.
    assert bi._split_booking_time("Mitgliedsbeitrag 2024") == ("Mitgliedsbeitrag 2024", None)
    assert bi._split_booking_time(None) == (None, None)


def test_format_iban() -> None:
    assert bi.format_iban("DE70120300001076878808") == "DE70 1203 0000 1076 8788 08"
    assert bi.format_iban("nl70citi2032329018") == "NL70 CITI 2032 3290 18"
    assert bi.format_iban(None) is None


def test_build_short_description() -> None:
    assert (
        bi.build_short_description("Quentin Walz", "AStA-Aufwandsentschädigung 03/26")
        == "AStA-Aufwandsentschädigung 03/26 – Quentin Walz"
    )
    assert bi.build_short_description("Quentin Walz", None) == "Quentin Walz"
    assert bi.build_short_description(None, "Spende") == "Spende"
    assert bi.build_short_description(None, None) == "Bankumsatz"


def test_build_booking_note() -> None:
    note = bi.build_booking_note(
        name="Quentin Walz",
        iban="DE70120300001076878808",
        purpose="AStA-Aufwandsentschädigung 03/26",
        kind="expense",
        when=date(2026, 4, 3),
        booking_time="09:15",
    )
    assert note == (
        "Empfänger: Quentin Walz\n"
        "IBAN: DE70 1203 0000 1076 8788 08\n"
        "Zweck: AStA-Aufwandsentschädigung 03/26\n"
        "Buchung: 03.04.2026, 09:15 Uhr"
    )
    # income → „Absender"; ohne Uhrzeit nur Datum.
    income = bi.build_booking_note(
        name="oikos Bayreuth e.V.",
        iban=None,
        purpose="Spende",
        kind="income",
        when=date(2026, 6, 16),
        booking_time=None,
    )
    assert income == "Absender: oikos Bayreuth e.V.\nZweck: Spende\nBuchung: 16.06.2026"
    assert bi.build_booking_note(
        name=None, iban=None, purpose=None, kind="expense", when=None
    ) is None
