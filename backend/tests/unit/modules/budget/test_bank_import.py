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


def test_camt_sub_cent_rejected() -> None:
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt><Ntry>
 <Amt Ccy="EUR">100.005</Amt><CdtDbtInd>CRDT</CdtDbtInd>
</Ntry></Stmt></Document>"""
    with pytest.raises(bi.StatementParseError):
        bi.parse_camt053(xml)
