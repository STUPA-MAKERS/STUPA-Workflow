"""Sammelbuchungs-Anzeige (#fints-batch) + form-agnostische Client-Ergebnis-Auswertung."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.budget.bank import normalize
from app.modules.budget.bank.client import (
    lines_from_camt_documents,
    lines_from_fetch_result,
)
from app.modules.budget.bank.service import BankService
from app.modules.budget.bank.statement import StatementParseError

_CAMT_ONE = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.08">
 <BkToCstmrAcctRpt><Rpt>
  <Ntry><Amt Ccy="EUR">12.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
   <NtryDtls><TxDtls><RmtInf><Ustrd>Spende</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
 </Rpt></BkToCstmrAcctRpt></Document>"""
_CAMT_EMPTY = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.08">
 <BkToCstmrAcctRpt><Rpt></Rpt></BkToCstmrAcctRpt></Document>"""
_CAMT_UNUSABLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.08">
 <BkToCstmrAcctRpt><Rpt><Ntry><Amt Ccy="EUR">1.00</Amt></Ntry></Rpt>
 </BkToCstmrAcctRpt></Document>"""


# ------------------------------------------------------------------- prettify
@pytest.mark.parametrize(
    ("raw", "pretty"),
    [
        (
            "DATEI-NR. 0000794247 ANZAHL 00000002",
            "Sammelbuchung Datei-Nr. 794247 (2 Posten)",
        ),
        (
            "GUTSCHR. SAMMELUEBERW. DATEI-NR. 0000794247 ANZAHL 00000001 XY",
            "GUTSCHR. SAMMELUEBERW. Sammelbuchung Datei-Nr. 794247 (1 Posten) XY",
        ),
        ("datei-nr 12 anzahl 3", "Sammelbuchung Datei-Nr. 12 (3 Posten)"),
        ("Miete Mai", "Miete Mai"),
        ("DATEI-NR. 123", "DATEI-NR. 123"),  # ohne ANZAHL kein Sammel-Muster
        (None, None),
        ("", ""),
    ],
)
def test_prettify_purpose(raw: str | None, pretty: str | None) -> None:
    assert normalize.prettify_purpose(raw) == pretty


def test_prettify_flows_into_description_note_and_line_out() -> None:
    raw = "DATEI-NR. 0000000012 ANZAHL 00000003"
    assert (
        normalize.build_short_description(None, raw)
        == "Sammelbuchung Datei-Nr. 12 (3 Posten)"
    )
    note = normalize.build_booking_note(
        name=None, iban=None, purpose=raw, kind="expense", when=None
    )
    assert note == "Zweck: Sammelbuchung Datei-Nr. 12 (3 Posten)"
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.modules.budget.tree_models import BankStatementLine

    line = BankStatementLine(
        id=uuid4(),
        account_id=uuid4(),
        idempotency_key="k",
        amount=Decimal("-500.00"),
        currency="EUR",
        match_state="unmatched",
        purpose=raw,
        raw_payload={"creditDebit": "DBIT"},
    )
    line.created_at = datetime(2026, 6, 30, tzinfo=UTC)
    assert BankService._line_out(line, None).purpose == (
        "Sammelbuchung Datei-Nr. 12 (3 Posten)"
    )


# ------------------------------------------------------------- fetch results
def test_lines_from_fetch_result_camt_tuple() -> None:
    lines = lines_from_fetch_result(([_CAMT_ONE], [None]))
    assert [line.amount for line in lines] == [Decimal("12.00")]


def test_lines_from_fetch_result_mt940_iterable() -> None:
    tx = SimpleNamespace(
        data={"amount": SimpleNamespace(amount="10.00", currency="EUR"), "status": "C"}
    )
    lines = lines_from_fetch_result([tx])
    assert [line.amount for line in lines] == [Decimal("10.00")]


def test_lines_from_camt_documents_tolerates_empty_docs() -> None:
    lines = lines_from_camt_documents([b"", _CAMT_EMPTY, _CAMT_UNUSABLE, _CAMT_ONE])
    assert [line.amount for line in lines] == [Decimal("12.00")]


def test_lines_from_camt_documents_raises_on_junk() -> None:
    with pytest.raises(StatementParseError):
        lines_from_camt_documents([b"not xml at all"])
