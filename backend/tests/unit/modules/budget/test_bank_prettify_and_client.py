"""Sammelbuchungs-Anzeige (#fints-batch) + form-agnostische Client-Ergebnis-Auswertung."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.budget.bank import normalize
from app.modules.budget.bank.camt_parse import parse_camt
from app.modules.budget.bank.client import (
    lines_from_camt_documents,
    lines_from_fetch_result,
)
from app.modules.budget.bank.service import BankService
from app.modules.budget.bank.statement import StatementParseError

# Combined camt.053 (ONE HKCAZ fetch, two accounts) — Sparkasse returns this even
# for an account-scoped request. Each <Stmt> carries its own <Acct>/<IBAN>.
_CAMT_COMBINED = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">
 <BkToCstmrStmt>
  <Stmt><Acct><Id><IBAN>DE11111111111111111111</IBAN></Id></Acct>
   <Ntry><Amt Ccy="EUR">10.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
    <NtryDtls><TxDtls><RmtInf><Ustrd>KontoA</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
  </Stmt>
  <Stmt><Acct><Id><IBAN>DE22222222222222222222</IBAN></Id></Acct>
   <Ntry><Amt Ccy="EUR">20.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
    <NtryDtls><TxDtls><RmtInf><Ustrd>KontoB</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
  </Stmt>
 </BkToCstmrStmt></Document>"""
# A statement WITHOUT an identifiable account IBAN — must never be filtered out.
_CAMT_NO_ACCT = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">
 <BkToCstmrStmt><Stmt>
   <Ntry><Amt Ccy="EUR">5.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
    <NtryDtls><TxDtls><RmtInf><Ustrd>NoAcct</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
 </Stmt></BkToCstmrStmt></Document>"""
# Statements identified only by the proprietary account NUMBER (no IBAN) — older
# Sparkasse SEPA accounts. Scoping must work by account number too.
_CAMT_OTHR = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">
 <BkToCstmrStmt>
  <Stmt><Acct><Id><Othr><Id>1234567</Id></Othr></Id></Acct>
   <Ntry><Amt Ccy="EUR">10.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
    <NtryDtls><TxDtls><RmtInf><Ustrd>KontoA</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
  </Stmt>
  <Stmt><Acct><Id><Othr><Id>7654321</Id></Othr></Id></Acct>
   <Ntry><Amt Ccy="EUR">20.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
    <NtryDtls><TxDtls><RmtInf><Ustrd>KontoB</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
  </Stmt>
 </BkToCstmrStmt></Document>"""

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


# ------------------------------------------------- account scoping (#konten all-accounts)
def test_parse_camt_scopes_to_requested_iban() -> None:
    """A combined camt.053 is filtered to the selected account (spaces tolerated)."""
    only_a = parse_camt(_CAMT_COMBINED, iban="DE11 1111 1111 1111 1111 11")
    assert [line.amount for line in only_a] == [Decimal("10.00")]
    only_b = parse_camt(_CAMT_COMBINED, iban="de22222222222222222222")
    assert [line.amount for line in only_b] == [Decimal("20.00")]


def test_parse_camt_scopes_by_account_number_without_iban() -> None:
    """Older Sparkasse accounts have no IBAN — scope by the account number."""
    only_a = parse_camt(_CAMT_OTHR, account_ids=["1234567"])
    assert [line.amount for line in only_a] == [Decimal("10.00")]


def test_parse_camt_without_scope_keeps_all_statements() -> None:
    lines = parse_camt(_CAMT_COMBINED)
    assert sorted(line.amount for line in lines) == [Decimal("10.00"), Decimal("20.00")]
    empty_scope = parse_camt(_CAMT_COMBINED, account_ids=[""])  # blank ids ignored
    assert len(empty_scope) == 2


def test_parse_camt_keeps_statement_without_identifiable_account() -> None:
    """Defensive: a scoped fetch must not drop a statement that omits its account."""
    lines = parse_camt(_CAMT_NO_ACCT, iban="DE11111111111111111111")
    assert [line.amount for line in lines] == [Decimal("5.00")]


def test_parse_camt_nonmatching_scope_yields_no_entries() -> None:
    with pytest.raises(StatementParseError):
        parse_camt(_CAMT_COMBINED, iban="DE99999999999999999999")


def test_lines_from_fetch_result_scopes_camt_by_account_ids() -> None:
    lines = lines_from_fetch_result(([_CAMT_COMBINED], [None]), ["DE22222222222222222222"])
    assert [line.amount for line in lines] == [Decimal("20.00")]


def test_statement_account_ids_lists_all_accounts() -> None:
    """Diagnostic helper: reveals every account present in a fetched document."""
    from app.modules.budget.bank.camt_parse import statement_account_ids

    assert statement_account_ids(_CAMT_COMBINED) == [
        "DE11111111111111111111",
        "DE22222222222222222222",
    ]
    assert statement_account_ids(_CAMT_OTHR) == ["1234567", "7654321"]
    assert statement_account_ids(b"not xml") == []
