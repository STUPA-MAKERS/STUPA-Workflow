"""Bank statement parser (#fints): MT940, CAMT.053 and idempotency. Pure unit tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.budget.bank import camt_parse, dedup, mt940_parse, normalize, statement

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
    lines = mt940_parse.parse_mt940(_MT940)
    assert len(lines) == 2
    debit, credit = lines
    assert debit.amount == Decimal("-50.00")  # debit → negative
    assert credit.amount == Decimal("200.00")  # credit → positive
    assert debit.value_date == date(2024, 1, 2)
    assert "Miete Mai" in (debit.purpose or "")
    assert debit.counterparty_name == "MUSTERMANN GMBH"


def test_parse_camt_credit_debit_counterparty_and_notprovided() -> None:
    lines = camt_parse.parse_camt(_CAMT)
    assert len(lines) == 2
    debit, credit = lines
    assert debit.amount == Decimal("-50.00")
    assert debit.counterparty_iban == "DE89370400440532013000"
    assert debit.end_to_end_id is None  # NOTPROVIDED → empty
    assert credit.amount == Decimal("200.00")
    assert credit.counterparty_name == "ERIKA MUSTERFRAU"
    assert credit.end_to_end_id == "E2E-7788"
    assert credit.bank_ref == "BANKREF002"


def test_parse_statement_dispatch() -> None:
    assert len(statement.parse_statement(_CAMT, filename="x.xml")) == 2
    assert len(statement.parse_statement(_MT940, filename="x.sta")) == 2
    # The parser detects XML without a file extension by its content.
    assert len(statement.parse_statement(_CAMT)) == 2


def test_parse_errors() -> None:
    with pytest.raises(statement.StatementParseError):
        statement.parse_statement(b"")
    with pytest.raises(statement.StatementParseError):
        camt_parse.parse_camt(b"<Document></Document>")
    with pytest.raises(statement.StatementParseError):
        camt_parse.parse_camt(b"<<<not xml")
    with pytest.raises(statement.StatementParseError):
        mt940_parse.parse_mt940(b"garbage without tags")


def test_assign_keys_uses_bank_ref_when_present() -> None:
    lines = camt_parse.parse_camt(_CAMT)
    dedup.assign_keys("DE-ACCT", lines)
    assert all(line.idempotency_key for line in lines)
    # Parse and key a second time → the same keys (idempotent).
    again = camt_parse.parse_camt(_CAMT)
    dedup.assign_keys("DE-ACCT", again)
    assert [line.idempotency_key for line in lines] == [line.idempotency_key for line in again]


def test_assign_keys_disambiguates_identical_lines_without_ref() -> None:
    a = statement.StatementLine(
        amount=Decimal("-5.00"), value_date=date(2024, 5, 1), purpose="Kaffee"
    )
    b = statement.StatementLine(
        amount=Decimal("-5.00"), value_date=date(2024, 5, 1), purpose="Kaffee"
    )
    dedup.assign_keys("scope", [a, b])
    assert a.idempotency_key != b.idempotency_key  # the intraday sequence splits twins


def test_amount_out_of_range_rejected() -> None:
    huge = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt><Ntry>
 <Amt Ccy="EUR">99999999999.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
</Ntry></Stmt></Document>"""
    with pytest.raises(statement.StatementParseError):
        camt_parse.parse_camt(huge)


class _Amt:
    def __init__(self, amount: str, currency: str = "EUR") -> None:
        self.amount = Decimal(amount)
        self.currency = currency


class _Tx:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data


def test_mt940_sign_from_status() -> None:
    """Take the sign from the status, including the RC and RD reversal markers."""
    def amt(status: str, value: str = "50.00") -> Decimal:
        return mt940_parse.lines_from_mt940_transactions(
            [_Tx({"amount": _Amt(value), "status": status})]
        )[0].amount

    assert amt("D") == Decimal("-50.00")
    assert amt("C") == Decimal("50.00")
    # An RC status reverses a credit, so the money goes out → negative (the real bug fix).
    assert amt("RC") == Decimal("-50.00")
    # An RD status reverses a debit, so the money comes in → positive.
    assert amt("RD") == Decimal("50.00")
    # An unknown or empty status keeps the sign of the library (negative here).
    neg = mt940_parse.lines_from_mt940_transactions([_Tx({"amount": _Amt("-7.00")})])[0]
    assert neg.amount == Decimal("-7.00")


def test_mt940_booking_time_lands_in_raw() -> None:
    """Move the Sparkasse `DATUM ... UHR` suffix out of the purpose.

    The parser cleans the purpose and writes the time to `raw['booking_time']`. The
    `Buchung:` line of the booking note reads that value (#fints).
    """
    line = mt940_parse.lines_from_mt940_transactions(
        [_Tx({
            "amount": _Amt("50.00"),
            "status": "C",
            "purpose": "Miete Mai DATUM 03.04.2026, 09.15 UHR",
        })]
    )[0]
    assert line.purpose == "Miete Mai"
    assert line.raw.get("booking_time") == "09:15"


def test_balance_from_mt940_out_of_range_amount() -> None:
    """A balance outside the valid amount range gives None instead of a crash."""
    bal = SimpleNamespace(amount=_Amt("99999999999.00"), date=None)
    assert mt940_parse.balance_from_mt940(bal) is None


def test_mt940_closing_balance_non_dict_data() -> None:
    """A non-dict `transactions.data` (unexpected library shape) gives no balance."""
    assert mt940_parse.mt940_closing_balance(SimpleNamespace(data=["kein", "dict"])) is None


def test_camt_closing_balance_unparseable_xml() -> None:
    """Broken XML in the balance path gives None. The line parser reports the error."""
    assert camt_parse.camt_closing_balance(b"<<<not xml") is None


def test_camt_closing_balance_non_decimal_amount() -> None:
    """A CLBD with a non-numeric <Amt> text gives no balance. The lines stay parsed."""
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt>
 <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">abc</Amt>
  <CdtDbtInd>CRDT</CdtDbtInd></Bal>
 <Ntry><Amt Ccy="EUR">50.00</Amt><CdtDbtInd>DBIT</CdtDbtInd></Ntry>
</Stmt></Document>"""
    lines, bal = statement.parse_statement_full(xml)
    assert len(lines) == 1
    assert bal is None


def test_iban_mod97_rejects_non_base36_chars() -> None:
    """A candidate with non-base36 characters, such as umlauts, is not a valid IBAN."""
    assert normalize._iban_mod97_ok("DE12ÄÖÜ4050000010008395") is False


def test_split_leading_iban_full_length_bad_checksum() -> None:
    """A full DE IBAN length with a wrong mod-97 checksum gives no split.

    A DE00 prefix is never valid, so the name stays untouched.
    """
    assert normalize.split_leading_iban("DE00120300001076878808Quentin Walz", None) == (
        "DE00120300001076878808Quentin Walz",
        None,
    )


def test_camt_direction_edges() -> None:
    """Cover the direction edges of a CAMT entry.

    The parser skips an entry without an indicator. RvslInd turns the sign around. A
    negative <Amt> becomes its absolute value.
    """
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt>
 <Ntry><Amt Ccy="EUR">10.00</Amt></Ntry>
 <Ntry><Amt Ccy="EUR">20.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><RvslInd>true</RvslInd></Ntry>
 <Ntry><Amt Ccy="EUR">-30.00</Amt><CdtDbtInd>DBIT</CdtDbtInd></Ntry>
</Stmt></Document>"""
    lines = camt_parse.parse_camt(xml)
    assert len(lines) == 2  # the first entry has no CdtDbtInd and is skipped
    assert lines[0].amount == Decimal("-20.00")  # a reversed credit pays out
    assert lines[0].raw.get("reversal") == "true"
    assert lines[1].amount == Decimal("-30.00")  # negative <Amt> → abs, then DBIT


def test_parse_statement_full_mt940_balance() -> None:
    """The parser also delivers the MT940 closing balance (:62F:) (#fints-konten)."""
    lines, bal = statement.parse_statement_full(_MT940)
    assert len(lines) == 2
    assert bal is not None
    assert bal.amount == Decimal("1150.00")
    assert bal.currency == "EUR"
    assert bal.as_of == date(2024, 1, 3)


def test_camt_closing_balance_clbd_signed() -> None:
    """Read the CAMT closing balance from CLBD. CdtDbtInd sets the sign (DBIT → minus)."""
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt>
 <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">2500.00</Amt>
  <CdtDbtInd>DBIT</CdtDbtInd><Dt><Dt>2026-06-30</Dt></Dt></Bal>
 <Ntry><Amt Ccy="EUR">50.00</Amt><CdtDbtInd>DBIT</CdtDbtInd></Ntry>
</Stmt></Document>"""
    _lines, bal = statement.parse_statement_full(xml)
    assert bal is not None
    assert bal.amount == Decimal("-2500.00")  # DBIT → debit balance
    assert bal.as_of == date(2026, 6, 30)


def test_camt_no_balance() -> None:
    """Without a <Bal> element there is no balance. The lines still parse."""
    lines, bal = statement.parse_statement_full(_CAMT)
    assert len(lines) == 2
    assert bal is None


def test_balance_from_mt940_handles_missing() -> None:
    assert mt940_parse.balance_from_mt940(object()) is None  # no .amount


def test_normalize_purpose_unglues_subfields() -> None:
    """Split ?86 subfields that ran together (#fints)."""
    assert normalize.normalize_purpose("DATEI-NR. 0000794247ANZAHL 00000002") == (
        "DATEI-NR. 0000794247 ANZAHL 00000002"
    )
    assert normalize.normalize_purpose("Abrechnung 30.06.2026siehe Anlage") == (
        "Abrechnung 30.06.2026 siehe Anlage"
    )
    assert normalize.normalize_purpose(None) is None
    assert normalize.normalize_purpose("   ") is None


def test_normalize_then_split_strips_datum_suffix() -> None:
    """Detach the time suffix even without a space before `DATUM`."""
    purpose, time = normalize.split_booking_time(
        normalize.normalize_purpose("Asta-Aufwandsentschädigung 05/2026DATUM 09.06.2026, 15.54 UHR")
    )
    assert purpose == "Asta-Aufwandsentschädigung 05/2026"
    assert time == "15:54"


def test_canonical_purpose_key_ignores_spacing_and_punct() -> None:
    """The canonical key stays the same across spacing and punctuation (#fints-dedup)."""
    assert dedup.canonical_purpose_key("DATEI-NR. 0000794247ANZAHL 00000002") == (
        dedup.canonical_purpose_key("DATEI-NR. 0000794247 ANZAHL 00000002")
    )


def test_assign_keys_from_raw_stable_across_parser_versions() -> None:
    """Build the key from the RAW data (#fints-raw).

    Identical `raw` gives the SAME key, whatever the derived `purpose` and
    `counterparty_*` look like. This holds for an old and a new parser version. Without
    it, a re-import duplicates a line that the platform already booked.
    """
    raw = {"purpose": "oikos Spende", "applicant_name": "oikos Bayreuth e.V.",
           "applicant_iban": "DE85780608960006017410"}
    old = statement.StatementLine(  # old parse: IBAN glued into the name, other purpose
        amount=Decimal("-1377.27"), value_date=date(2026, 6, 26),
        counterparty_name="DE85780608960006017410oikos Bayreuth e.V.",
        counterparty_iban=None, purpose="oikos SpendeDATUM 01.01.2026, 10.00 UHR", raw=dict(raw),
    )
    new = statement.StatementLine(  # new parse: clean, but the SAME raw
        amount=Decimal("-1377.27"), value_date=date(2026, 6, 26),
        counterparty_name="oikos Bayreuth e.V.",
        counterparty_iban="DE85780608960006017410", purpose="oikos Spende", raw=dict(raw),
    )
    dedup.assign_keys("acc", [old])
    dedup.assign_keys("acc", [new])
    assert old.idempotency_key == new.idempotency_key


def test_assign_keys_distinct_for_different_raw_counterparty() -> None:
    """Real single payments with another raw originator get DIFFERENT keys.

    The code must not merge them by mistake (#fints-raw).
    """
    a = statement.StatementLine(amount=Decimal("-80.00"), value_date=date(2026, 5, 26),
                         purpose="Aufwand", raw={"purpose": "Aufwand", "applicant_name": "Alice"})
    b = statement.StatementLine(amount=Decimal("-80.00"), value_date=date(2026, 5, 26),
                         purpose="Aufwand", raw={"purpose": "Aufwand", "applicant_name": "Bob"})
    dedup.assign_keys("acc", [a, b])
    assert a.idempotency_key != b.idempotency_key


def test_resolve_from_raw_helpers() -> None:
    """The resolve_* helpers work on the raw data.

    A non-dict value or a missing field returns a fallback signal.
    """
    # MT940 raw → clean counterparty (KRZL dropped) plus an unglued, stripped purpose
    name, iban = normalize.resolve_counterparty(
        {"applicant_name": "KRZL", "gvc_applicant_iban": "DE79640500000100083958"}, credit=False
    )
    assert name is None and iban == "DE79640500000100083958"
    assert normalize.resolve_purpose(
        {"purpose": "Re 0000794247ANZAHL 2"}
    ) == "Re 0000794247 ANZAHL 2"
    # CAMT raw, no dict or no purpose → None signals (the caller uses the column)
    assert normalize.resolve_counterparty(None, credit=True) == (None, None)
    assert normalize.resolve_counterparty({"creditDebit": "CRDT"}, credit=True) == (None, None)
    assert normalize.resolve_purpose(None) is None
    assert normalize.resolve_purpose({"creditDebit": "CRDT"}) is None


def test_mt940_counterparty_drops_krzl_glued_to_iban() -> None:
    """A real batch booking puts "<IBAN>KRZL" into `applicant_name` and has no own ?31.

    The parser first splits the IBAN and only then drops "KRZL". The result is
    (None, IBAN), not "KRZL" (#fints-raw).
    """
    name, iban = normalize.mt940_counterparty(
        {"applicant_name": "DE79640500000100083958KRZL"}, credit=False
    )
    assert name is None
    assert iban == "DE79640500000100083958"


def test_mt940_counterparty_drops_krzl_placeholder() -> None:
    """The "KRZL" placeholder of a batch or file booking never becomes the counterparty."""
    name, iban = normalize.mt940_counterparty(
        {"applicant_name": "KRZL", "gvc_applicant_iban": "DE79640500000100083958"},
        credit=False,
    )
    assert name is None
    assert iban == "DE79640500000100083958"


def test_camt_balance_clav_fallback_and_skips_codeless() -> None:
    """Without CLBD the parser falls back to CLAV. It skips a <Bal> without a code."""
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt>
 <Bal><Amt Ccy="EUR">1.00</Amt></Bal>
 <Bal><Tp><CdOrPrtry><Cd>CLAV</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">300.00</Amt>
  <CdtDbtInd>CRDT</CdtDbtInd></Bal>
 <Ntry><Amt Ccy="EUR">50.00</Amt><CdtDbtInd>DBIT</CdtDbtInd></Ntry>
</Stmt></Document>"""
    _lines, bal = statement.parse_statement_full(xml)
    assert bal is not None
    assert bal.amount == Decimal("300.00")


def test_camt_balance_unparseable_amount_ignored() -> None:
    """A CLBD without a usable amount gives no balance. The lines stay parsed."""
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt>
 <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp></Bal>
 <Ntry><Amt Ccy="EUR">50.00</Amt><CdtDbtInd>DBIT</CdtDbtInd></Ntry>
</Stmt></Document>"""
    _lines, bal = statement.parse_statement_full(xml)
    assert bal is None


def test_camt_sub_cent_rejected() -> None:
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt><Ntry>
 <Amt Ccy="EUR">100.005</Amt><CdtDbtInd>CRDT</CdtDbtInd>
</Ntry></Stmt></Document>"""
    with pytest.raises(statement.StatementParseError):
        camt_parse.parse_camt(xml)


def test_split_leading_iban() -> None:
    """Split a counterparty IBAN and a name that share one field (#fints)."""
    # Empty IBAN field, name starts with a full valid DE IBAN → the parser splits it.
    assert normalize.split_leading_iban("DE70120300001076878808Quentin Walz", None) == (
        "Quentin Walz",
        "DE70120300001076878808",
    )
    # An NL IBAN carries letters in the BBAN (CITI). The old digits-only heuristic failed
    # here. The length table plus the checksum splits it correctly (#fints).
    assert normalize.split_leading_iban("NL70CITI2032329018Stichting Mollie Payments", None) == (
        "Stichting Mollie Payments",
        "NL70CITI2032329018",
    )
    # The name field holds only an IBAN → the name is None and the IBAN is set.
    assert normalize.split_leading_iban("DE89370400440532013000", None) == (
        None,
        "DE89370400440532013000",
    )
    # A wrong checksum or a short value is NOT read as an IBAN. The name stays untouched.
    assert normalize.split_leading_iban("DE85780608960006017", None) == (
        "DE85780608960006017",
        None,
    )
    # A reference that only looks like an IBAN (no valid country code) → no split.
    assert normalize.split_leading_iban("RF1234567890Acme", None) == ("RF1234567890Acme", None)
    # The IBAN field is set and repeats in the name → strip the prefix.
    assert normalize.split_leading_iban("DE111Heldenwerbung", "DE111") == (
        "Heldenwerbung",
        "DE111",
    )
    # Clean separate fields stay unchanged.
    assert normalize.split_leading_iban("Quentin Walz", "DE70120300001076878808") == (
        "Quentin Walz",
        "DE70120300001076878808",
    )
    # No name → (None, IBAN). A plain name without an IBAN stays unchanged.
    assert normalize.split_leading_iban(None, "DE111") == (None, "DE111")
    assert normalize.split_leading_iban("Plain Name", None) == ("Plain Name", None)


def test_mt940_counterparty_prefers_sepa_fields() -> None:
    """Take the real counterparty of a salary or SEPA transaction from the SEPA fields.

    The parser reads ABWE+, ABWA+ and IBAN+. It does not use the short code in ?32
    (#fints).
    """
    # Outgoing salary: ?32 holds only a short code and ?31 is empty. The real recipient
    # sits in ABWE+ and the IBAN in IBAN+.
    salary = {
        "applicant_name": "KRZL",
        "applicant_iban": None,
        "deviate_recipient": "Max Mustermann",
        "gvc_applicant_iban": "DE70120300001076878808",
    }
    assert normalize.mt940_counterparty(salary, credit=False) == (
        "Max Mustermann",
        "DE70120300001076878808",
    )
    # Incoming: the deviating originator (ABWA+) wins.
    incoming = {"applicant_name": "KRZL", "deviate_applicant": "ACME GmbH"}
    assert normalize.mt940_counterparty(incoming, credit=True) == ("ACME GmbH", None)
    # Without the deviating fields: fall back to ?32, and to ?31 before IBAN+.
    plain = {
        "applicant_name": "Quentin Walz",
        "applicant_iban": "DE89370400440532013000",
        "gvc_applicant_iban": "DE111",
    }
    assert normalize.mt940_counterparty(plain, credit=False) == (
        "Quentin Walz",
        "DE89370400440532013000",
    )
    # Fully empty → (None, None).
    assert normalize.mt940_counterparty({}, credit=False) == (None, None)


def test_split_booking_time() -> None:
    """Detach the Sparkasse suffix "... DATUM dd.mm.yyyy, hh.mm UHR" from the purpose."""
    assert normalize.split_booking_time(
        "AStA-Aufwandsentschädigung 03/26DATUM 03.04.2026, 09.15 UHR"
    ) == ("AStA-Aufwandsentschädigung 03/26", "09:15")
    # A time with a colon and lowercase text also matches.
    assert normalize.split_booking_time("Miete Mai datum 01.05.2026 08:00 uhr") == (
        "Miete Mai",
        "08:00",
    )
    # Without the suffix nothing changes. None stays None.
    assert normalize.split_booking_time("Mitgliedsbeitrag 2024") == ("Mitgliedsbeitrag 2024", None)
    assert normalize.split_booking_time(None) == (None, None)


def test_format_iban() -> None:
    assert normalize.format_iban("DE70120300001076878808") == "DE70 1203 0000 1076 8788 08"
    assert normalize.format_iban("nl70citi2032329018") == "NL70 CITI 2032 3290 18"
    assert normalize.format_iban(None) is None


def test_build_short_description() -> None:
    assert (
        normalize.build_short_description("Quentin Walz", "AStA-Aufwandsentschädigung 03/26")
        == "AStA-Aufwandsentschädigung 03/26 – Quentin Walz"
    )
    assert normalize.build_short_description("Quentin Walz", None) == "Quentin Walz"
    assert normalize.build_short_description(None, "Spende") == "Spende"
    assert normalize.build_short_description(None, None) == "Bankumsatz"


def test_build_booking_note() -> None:
    note = normalize.build_booking_note(
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
    # income → "Absender". Without a time, only the date shows.
    income = normalize.build_booking_note(
        name="oikos Bayreuth e.V.",
        iban=None,
        purpose="Spende",
        kind="income",
        when=date(2026, 6, 16),
        booking_time=None,
    )
    assert income == "Absender: oikos Bayreuth e.V.\nZweck: Spende\nBuchung: 16.06.2026"
    assert normalize.build_booking_note(
        name=None, iban=None, purpose=None, kind="expense", when=None
    ) is None
