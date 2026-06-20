"""Ergänzende #fints-Tests: Parser-Helfer + Matcher-Vorschlag + Service-Zweige."""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.modules.budget import bank_import as bi
from app.modules.budget import bank_service
from app.modules.budget import fints_client as fc
from app.modules.budget.bank_service import BankService
from app.modules.budget.tree_models import BudgetExpense
from app.modules.budget.tree_schemas import ConfirmLineRequest
from app.settings import load_settings
from app.shared.crypto import encrypt_secret
from app.shared.errors import NotFoundError, ServiceUnavailableError, ValidationProblem

from .test_bank_service import _KEY, _account, _line, _Result, _Session  # Wiederverwendung


# ----------------------------------------------------------- bank_import helpers
def test_clean_and_skip_notprovided() -> None:
    assert bi._clean(None) is None
    assert bi._clean("  x ") == "x"
    assert bi._clean("   ") is None
    assert bi._skip_notprovided("NOTPROVIDED") is None
    assert bi._skip_notprovided("RF99") == "RF99"
    assert bi._skip_notprovided(None) is None


def test_as_date_and_camt_date() -> None:
    assert bi._as_date(None) is None
    assert bi._as_date("not a date") is None
    assert bi._as_date(date(2024, 1, 2)) == date(2024, 1, 2)
    assert bi._camt_date(None) is None
    el = ET.fromstring("<ValDt><Dt>2024-03-04</Dt></ValDt>")
    assert bi._camt_date(el) == date(2024, 3, 4)
    bad = ET.fromstring("<ValDt><Dt>nope</Dt></ValDt>")
    assert bi._camt_date(bad) is None
    empty = ET.fromstring("<ValDt></ValDt>")
    assert bi._camt_date(empty) is None


def test_line_from_mt940_data_no_amount() -> None:
    assert bi._line_from_mt940_data({}) is None


def test_lines_from_mt940_skips_amountless() -> None:
    class _Amt:
        amount = Decimal("5.00")
        currency = "EUR"

    class _Tx:
        def __init__(self, data: dict[str, Any]) -> None:
            self.data = data

    out = bi.lines_from_mt940_transactions([_Tx({}), _Tx({"amount": _Amt()})])
    assert len(out) == 1  # die amount-lose Transaktion wird übersprungen


def test_find_local_none() -> None:
    assert bi._find_local(None, "X") is None


def test_camt_date_invalid_calendar_date() -> None:
    # len >= 10, aber kein gültiges Datum → ValueError-Zweig.
    el = ET.fromstring("<ValDt><Dt>2024-13-45</Dt></ValDt>")
    assert bi._camt_date(el) is None


def test_decode_latin1_fallback() -> None:
    # 0xFF ist kein gültiges UTF-8 → latin-1-Fallback greift.
    assert "ÿ" in bi._decode(b"\xff")


def test_camt_skips_entries_without_usable_amount() -> None:
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt>
 <Ntry><CdtDbtInd>CRDT</CdtDbtInd></Ntry>
 <Ntry><Amt Ccy="EUR">nope</Amt><CdtDbtInd>CRDT</CdtDbtInd></Ntry>
</Stmt></Document>"""
    with pytest.raises(bi.StatementParseError):
        bi.parse_camt053(xml)


def test_parse_statement_mt940_without_filename() -> None:
    mt = (
        b":20:X\n:25:1/2\n:60F:C240101EUR0,00\n"
        b":61:2401010101CR1,00NTRFNONREF\n:86:051?20Test\n:62F:C240101EUR1,00\n-"
    )
    lines = bi.parse_statement(mt)
    assert lines and lines[0].amount == Decimal("1.00")


# ----------------------------------------------------------- service branches
def _svc(session: _Session, monkeypatch: pytest.MonkeyPatch) -> BankService:
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(bank_service, "audit_record", _noop)
    settings = load_settings(fints_enc_key=_KEY)
    return BankService(session, settings=settings, actor="t")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_suggest_matches_existing_expense(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    exp = BudgetExpense(
        id=uuid.uuid4(), budget_id=uuid.uuid4(), fiscal_year_id=uuid.uuid4(),
        kind="expense", amount=Decimal("50.00"), currency="EUR", description="x",
    )
    exp.payment_date = date(2024, 1, 2)
    exp.reference_number = "RG-1"
    session.execute_q.append(_Result([exp]))  # _suggest candidate query
    line = bi.StatementLine(
        amount=Decimal("-50.00"), value_date=date(2024, 1, 2), reference="RG1"
    )
    budget_id, expense_id = await svc._suggest(line)
    assert expense_id == exp.id
    assert budget_id == exp.budget_id


@pytest.mark.asyncio
async def test_suggest_falls_back_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    mem_budget = uuid.uuid4()
    session.execute_q.append(_Result([]))  # keine Buchungs-Kandidaten
    session.scalar_q.append(mem_budget)  # Gegen-IBAN-Gedächtnis
    line = bi.StatementLine(amount=Decimal("10.00"), counterparty_iban="DEXP")
    budget_id, expense_id = await svc._suggest(line)
    assert expense_id is None
    assert budget_id == mem_budget


@pytest.mark.asyncio
async def test_memory_budget_no_iban(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(_Session(), monkeypatch)
    assert await svc._memory_budget(None) is None


@pytest.mark.asyncio
async def test_list_lines_with_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line(amount=Decimal("-9.00"))  # kind expense, kein suggested budget
    session.scalars_q.append(_Result([line]))
    out = await svc.list_lines(account_id=uuid.uuid4(), state="unmatched")
    assert len(out) == 1
    assert out[0].kind == "expense"
    assert out[0].suggested_path_key is None


@pytest.mark.asyncio
async def test_confirm_line_description_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    from app.modules.budget.tree_schemas import ConfirmLineRequest, ExpenseOut
    from app.modules.budget.tree_service import BudgetTreeService

    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line()
    session.put(line)
    seen: dict[str, Any] = {}

    async def _book(self: Any, payload: Any, *, actor: str, commit: bool = True) -> ExpenseOut:
        seen["description"] = payload.description
        return ExpenseOut(
            id=uuid.uuid4(), budgetId=uuid.uuid4(), fiscalYearId=uuid.uuid4(),
            kind="expense", amount=Decimal("50.00"), currency="EUR",
            description=payload.description, createdAt=datetime(2024, 1, 1, tzinfo=UTC),
        )

    monkeypatch.setattr(BudgetTreeService, "book_expense", _book)
    # claim gewinnt; kein counterparty_iban → kein _remember_counterparty
    session.execute_q.append(_Result([(line.id,)]))
    await svc.confirm_line(
        line.id, ConfirmLineRequest(budgetId=uuid.uuid4(), description="Eigene Notiz")
    )
    assert seen["description"] == "Eigene Notiz"


def test_line_out_income_kind() -> None:
    line = _line(amount=Decimal("12.50"))
    out = BankService._line_out(line, "VS-1")
    assert out.kind == "income"
    assert out.suggested_path_key == "VS-1"


@pytest.mark.asyncio
async def test_sync_done_without_new_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.budget import fints_client as fc

    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = _account()
    session.put(acc)

    def _start(creds: Any, *, start_date: Any) -> fc.FintsOutcome:
        return fc.FintsOutcome(status="done", new_state=None, lines=[])

    monkeypatch.setattr(fc, "start_sync", _start)
    res = await svc.sync_account(acc.id)
    assert res.status == "done"
    assert res.imported == 0


@pytest.mark.asyncio
async def test_submit_tan_still_needs_tan(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.budget import fints_client as fc

    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = _account()
    session.put(acc)
    token = uuid.uuid4()
    out = fc.FintsOutcome(
        status="needs_tan", tan_mechanism="962", client_data=b"c", dialog_data=b"d", tan_data=b"t",
        decoupled=True,
    )
    await svc._store_session(acc.id, out, token=token)
    stored = session.added[-1]
    stored.id = token
    session.put(stored)
    def _submit(creds: Any, pending: Any, tan: str) -> fc.FintsOutcome:
        return fc.FintsOutcome(
            status="needs_tan", tan_mechanism="962", client_data=b"c", dialog_data=b"d",
            tan_data=b"t", decoupled=True,
        )

    monkeypatch.setattr(fc, "submit_tan", _submit)
    res = await svc.submit_tan(acc.id, token, "")
    assert res.status == "needs_tan"
    assert res.session_token == token


def test_matcher_far_date_branch() -> None:
    from app.modules.budget import bank_match as bm

    cand = bm.ExpenseCandidate(
        expense_id="e", budget_id="b", amount=Decimal("50.00"), when=date(2023, 1, 1),
        reference=None,
    )
    r = bm.score_candidate(
        line_amount=Decimal("-50.00"), line_when=date(2024, 6, 1),
        line_ref=None, line_e2e=None, candidate=cand,
    )
    assert "entfernt" in r.reason  # > _WIDE_DAYS-Zweig


def test_matcher_wide_window_branch() -> None:
    from app.modules.budget import bank_match as bm

    # delta = 4 Tage: zwischen _TIGHT_DAYS(2) und _WIDE_DAYS(5) → mittlerer Datums-Score.
    cand = bm.ExpenseCandidate(
        expense_id="e", budget_id="b", amount=Decimal("50.00"), when=date(2024, 1, 6),
        reference=None,
    )
    r = bm.score_candidate(
        line_amount=Decimal("-50.00"), line_when=date(2024, 1, 2),
        line_ref=None, line_e2e=None, candidate=cand,
    )
    assert "±4" in r.reason


@pytest.mark.asyncio
async def test_load_session_not_found_and_wrong_account(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.budget import fints_client as fc

    session = _Session()
    svc = _svc(session, monkeypatch)
    # gar keine Sitzung → NotFoundError
    with pytest.raises(NotFoundError):
        await svc._load_session(uuid.uuid4(), uuid.uuid4())
    # Sitzung existiert, aber falsches Konto → NotFoundError (Konto-Mismatch-Zweig)
    token = uuid.uuid4()
    out = fc.FintsOutcome(
        status="needs_tan", tan_mechanism="962", client_data=b"c", dialog_data=b"d", tan_data=b"t",
    )
    await svc._store_session(uuid.uuid4(), out, token=token)
    stored = session.added[-1]
    stored.id = token
    session.put(stored)
    with pytest.raises(NotFoundError):
        await svc._load_session(token, uuid.uuid4())


# ----------------------------------------------------- review-fix branches (#fints-review)
def test_decode_state_roundtrip_and_failures() -> None:
    assert BankService._decode_state(None, key=_KEY) is None
    token = encrypt_secret("blob", key=_KEY)
    assert BankService._decode_state(token, key=_KEY) == b"blob"
    assert BankService._decode_state("garbage", key=_KEY) is None  # undecryptable → None


@pytest.mark.asyncio
async def test_sync_account_fints_error_503(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = _account()
    session.put(acc)

    def _boom(creds: Any, *, start_date: Any) -> Any:
        raise fc.FintsError("connection refused")

    monkeypatch.setattr(fc, "start_sync", _boom)
    with pytest.raises(ServiceUnavailableError):
        await svc.sync_account(acc.id)


@pytest.mark.asyncio
async def test_submit_tan_fints_error_503(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = _account()
    session.put(acc)
    token = uuid.uuid4()
    out = fc.FintsOutcome(
        status="needs_tan", tan_mechanism="962", client_data=b"c", dialog_data=b"d", tan_data=b"t",
    )
    await svc._store_session(acc.id, out, token=token)
    stored = session.added[-1]
    stored.id = token
    session.put(stored)

    def _boom(creds: Any, pending: Any, tan: str) -> Any:
        raise fc.FintsError("nope")

    monkeypatch.setattr(fc, "submit_tan", _boom)
    with pytest.raises(ServiceUnavailableError):
        await svc.submit_tan(acc.id, token, "123456")


@pytest.mark.asyncio
async def test_stage_lines_too_many(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(_Session(), monkeypatch)
    lines = [
        bi.StatementLine(amount=Decimal("1.00"))
        for _ in range(bank_service._MAX_STATEMENT_LINES + 1)
    ]
    with pytest.raises(ValidationProblem):
        await svc._stage_lines(_account(), lines)


@pytest.mark.asyncio
async def test_stage_lines_rejects_non_eur(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(_Session(), monkeypatch)
    lines = [bi.StatementLine(amount=Decimal("1.00"), currency="USD")]
    with pytest.raises(ValidationProblem):
        await svc._stage_lines(_account(), lines)


@pytest.mark.asyncio
async def test_confirm_line_claim_lost(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nebenläufiger Verlierer: Claim-UPDATE liefert 0 Zeilen → already_matched.
    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line()
    session.put(line)
    session.execute_q.append(_Result([]))  # Claim verloren
    with pytest.raises(ValidationProblem):
        await svc.confirm_line(line.id, ConfirmLineRequest(budgetId=uuid.uuid4()))


@pytest.mark.asyncio
async def test_confirm_line_zero_amount(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line(amount=Decimal("0.00"))
    session.put(line)
    with pytest.raises(ValidationProblem):
        await svc.confirm_line(line.id, ConfirmLineRequest(budgetId=uuid.uuid4()))


@pytest.mark.asyncio
async def test_confirm_line_amount_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line(amount=Decimal("-50.00"))
    session.put(line)
    exp = BudgetExpense(
        id=uuid.uuid4(), budget_id=uuid.uuid4(), fiscal_year_id=uuid.uuid4(),
        kind="expense", amount=Decimal("99.00"), currency="EUR", description="x",
    )
    session.put(exp)
    with pytest.raises(ValidationProblem):
        await svc.confirm_line(line.id, ConfirmLineRequest(matchExpenseId=exp.id))


@pytest.mark.asyncio
async def test_confirm_line_already_allocated(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line(amount=Decimal("-50.00"))
    session.put(line)
    exp = BudgetExpense(
        id=uuid.uuid4(), budget_id=uuid.uuid4(), fiscal_year_id=uuid.uuid4(),
        kind="expense", amount=Decimal("50.00"), currency="EUR", description="x",
    )
    session.put(exp)
    session.scalar_q.append(uuid.uuid4())  # bereits zugeordnet
    with pytest.raises(ValidationProblem):
        await svc.confirm_line(line.id, ConfirmLineRequest(matchExpenseId=exp.id))


@pytest.mark.asyncio
async def test_confirm_line_booking_failure_reverts_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.budget.tree_service import BudgetTreeService

    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line()
    session.put(line)

    async def _boom(self: Any, payload: Any, *, actor: str, commit: bool = True) -> Any:
        raise RuntimeError("budget gone")

    monkeypatch.setattr(BudgetTreeService, "book_expense", _boom)
    session.execute_q.append(_Result([(line.id,)]))  # claim gewinnt, dann scheitert das Buchen
    with pytest.raises(RuntimeError):
        await svc.confirm_line(line.id, ConfirmLineRequest(budgetId=uuid.uuid4()))
    # Eine Transaktion → ein Rollback nimmt Claim + Buchung gemeinsam zurück.
    assert getattr(session, "rollbacks", 0) == 1


@pytest.mark.asyncio
async def test_ignore_line_rejects_matched(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line(match_state="matched")
    session.put(line)
    with pytest.raises(ValidationProblem):
        await svc.ignore_line(line.id)
