"""CAMT-Sammelbuchungs-Aufteilung (#fints-batch): ein ``Ntry`` mit n ``TxDtls``.

Deckt Split (Beträge/Richtung/Referenzen/Batch-Metadaten) und alle konservativen
Fallbacks (fehlender/kaputter/fremdwähriger Teilbetrag, Summen-Abweichung) ab.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.budget.bank import camt_parse

_HEAD = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.08">
 <BkToCstmrAcctRpt><Rpt>
"""
_TAIL = b"""
 </Rpt></BkToCstmrAcctRpt>
</Document>"""


def _doc(entry_xml: bytes) -> bytes:
    return _HEAD + entry_xml + _TAIL


_BATCH = _doc(b"""
  <Ntry>
   <Amt Ccy="EUR">500.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>
   <BookgDt><Dt>2026-06-30</Dt></BookgDt><ValDt><Dt>2026-06-30</Dt></ValDt>
   <AcctSvcrRef>ENTRYREF9</AcctSvcrRef>
   <AddtlNtryInf>SAMMELUEBERWEISUNG DATEI-NR. 0000794247 ANZAHL 00000002</AddtlNtryInf>
   <NtryDtls>
    <TxDtls>
     <Refs><AcctSvcrRef>SUBREF1</AcctSvcrRef><EndToEndId>E2E-A</EndToEndId></Refs>
     <AmtDtls><TxAmt><Amt Ccy="EUR">180.00</Amt></TxAmt></AmtDtls>
     <RltdPties><Cdtr><Nm>ALPHA GMBH</Nm></Cdtr>
       <CdtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></CdtrAcct></RltdPties>
     <RmtInf><Ustrd>Rechnung</Ustrd><Ustrd>4711</Ustrd></RmtInf>
    </TxDtls>
    <TxDtls>
     <Refs><EndToEndId>E2E-B</EndToEndId></Refs>
     <AmtDtls><TxAmt><Amt Ccy="EUR">320.00</Amt></TxAmt></AmtDtls>
     <RltdPties><Cdtr><Nm>BETA EV</Nm></Cdtr>
       <CdtrAcct><Id><IBAN>DE12500105170648489890</IBAN></Id></CdtrAcct></RltdPties>
     <RmtInf><Ustrd>Mitgliedsbeitrag</Ustrd></RmtInf>
    </TxDtls>
   </NtryDtls>
  </Ntry>""")


def test_batch_entry_splits_into_sub_transactions() -> None:
    lines = camt_parse.parse_camt(_BATCH)
    assert [line.amount for line in lines] == [Decimal("-180.00"), Decimal("-320.00")]
    first, second = lines
    assert first.purpose == "Rechnung 4711"  # mehrere Ustrd-Zeilen werden verbunden
    assert first.counterparty_name == "ALPHA GMBH"
    assert first.end_to_end_id == "E2E-A"
    assert second.counterparty_name == "BETA EV"
    # Bank-Referenz: je Teil-Transaktion (falls vorhanden), NIE die geteilte Eintrags-Referenz.
    assert first.bank_ref == "SUBREF1"
    assert second.bank_ref is None
    for line in lines:
        assert line.value_date == date(2026, 6, 30)
        assert line.raw["batch"] == "true"
        assert line.raw["batch_count"] == "2"
        assert line.raw["batch_total"] == "-500.00"
        assert line.raw["batch_ref"] == "ENTRYREF9"
        # Eintrags-Info (AddtlNtryInf) bleibt als Metadatum erhalten — das Staging
        # ersetzt damit die alte Gesamt-Zeile gezielt per Datei-Nr.
        assert line.raw["batch_info"] == "SAMMELUEBERWEISUNG DATEI-NR. 0000794247 ANZAHL 00000002"
        assert line.raw["purpose"] == line.purpose


def test_batch_sum_mismatch_falls_back_to_single_line() -> None:
    doc = _BATCH.replace(b">320.00<", b">300.00<")
    lines = camt_parse.parse_camt(doc)
    assert [line.amount for line in lines] == [Decimal("-500.00")]
    # Fallback nutzt die erste TxDtls als Detail-Quelle (bisheriges Verhalten).
    assert lines[0].counterparty_name == "ALPHA GMBH"
    assert "batch" not in lines[0].raw


@pytest.mark.parametrize(
    "mutation",
    [
        (b"<AmtDtls><TxAmt><Amt Ccy=\"EUR\">320.00</Amt></TxAmt></AmtDtls>", b""),
        (b"<Amt Ccy=\"EUR\">320.00</Amt>", b"<Amt Ccy=\"EUR\">notanumber</Amt>"),
        (b"<Amt Ccy=\"EUR\">320.00</Amt>", b"<Amt Ccy=\"USD\">320.00</Amt>"),
    ],
    ids=["missing-txamt", "invalid-decimal", "foreign-currency"],
)
def test_batch_unusable_sub_amount_falls_back(mutation: tuple[bytes, bytes]) -> None:
    old, new = mutation
    lines = camt_parse.parse_camt(_BATCH.replace(old, new))
    assert [line.amount for line in lines] == [Decimal("-500.00")]


def test_batch_sub_direction_override_and_reversal() -> None:
    # Gemischte Sammelbuchung: eine Gutschrift-Teilzahlung in einem Soll-Eintrag.
    doc = _doc(b"""
  <Ntry>
   <Amt Ccy="EUR">100.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>
   <ValDt><Dt>2026-06-30</Dt></ValDt>
   <NtryDtls>
    <TxDtls>
     <AmtDtls><TxAmt><Amt Ccy="EUR">150.00</Amt></TxAmt></AmtDtls>
     <CdtDbtInd>DBIT</CdtDbtInd>
    </TxDtls>
    <TxDtls>
     <AmtDtls><TxAmt><Amt Ccy="EUR">50.00</Amt></TxAmt></AmtDtls>
     <CdtDbtInd>CRDT</CdtDbtInd>
    </TxDtls>
   </NtryDtls>
  </Ntry>""")
    lines = camt_parse.parse_camt(doc)
    assert [line.amount for line in lines] == [Decimal("-150.00"), Decimal("50.00")]

    # Storno kehrt die Richtung aller Teil-Transaktionen um (wie beim ungeteilten Eintrag).
    reversed_doc = doc.replace(
        b"<CdtDbtInd>DBIT</CdtDbtInd>\n   <ValDt>",
        b"<CdtDbtInd>DBIT</CdtDbtInd><RvslInd>true</RvslInd>\n   <ValDt>",
    )
    lines = camt_parse.parse_camt(reversed_doc)
    assert [line.amount for line in lines] == [Decimal("150.00"), Decimal("-50.00")]


def test_single_txdtls_entry_keeps_addtlntryinf_fallback_purpose() -> None:
    doc = _doc(b"""
  <Ntry>
   <Amt Ccy="EUR">42.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
   <AddtlNtryInf>GUTSCHRIFT OHNE USTRD</AddtlNtryInf>
   <NtryDtls><TxDtls><Refs><EndToEndId>E2E-X</EndToEndId></Refs></TxDtls></NtryDtls>
  </Ntry>""")
    (line,) = camt_parse.parse_camt(doc)
    assert line.purpose == "GUTSCHRIFT OHNE USTRD"
    assert line.raw["purpose"] == "GUTSCHRIFT OHNE USTRD"
