"""Extra #fints tests: parser helpers, matcher suggestion and service branches."""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.modules.budget.bank import camt_parse, mt940_parse, normalize, service_base, statement
from app.modules.budget.bank import client as fc
from app.modules.budget.bank.service import BankService
from app.modules.budget.tree_models import BudgetExpense
from app.modules.budget.tree_schemas import ConfirmLineRequest
from app.settings import load_settings
from app.shared.crypto import encrypt_secret
from app.shared.errors import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationProblem,
)

from .test_bank_service import (  # reuse
    _KEY,
    _PID,
    _account,
    _cred,
    _line,
    _Result,
    _Session,
)


# bank_import helpers
def test_clean_and_skip_notprovided() -> None:
    assert normalize.clean(None) is None
    assert normalize.clean("  x ") == "x"
    assert normalize.clean("   ") is None
    assert normalize.skip_notprovided("NOTPROVIDED") is None
    assert normalize.skip_notprovided("RF99") == "RF99"
    assert normalize.skip_notprovided(None) is None


def test_as_date_and_camt_date() -> None:
    assert mt940_parse.as_date(None) is None
    assert mt940_parse.as_date("not a date") is None
    assert mt940_parse.as_date(date(2024, 1, 2)) == date(2024, 1, 2)
    assert camt_parse._camt_date(None) is None
    el = ET.fromstring("<ValDt><Dt>2024-03-04</Dt></ValDt>")
    assert camt_parse._camt_date(el) == date(2024, 3, 4)
    bad = ET.fromstring("<ValDt><Dt>nope</Dt></ValDt>")
    assert camt_parse._camt_date(bad) is None
    empty = ET.fromstring("<ValDt></ValDt>")
    assert camt_parse._camt_date(empty) is None


def test_line_from_mt940_data_no_amount() -> None:
    assert mt940_parse._line_from_mt940_data({}) is None


def test_lines_from_mt940_skips_amountless() -> None:
    class _Amt:
        amount = Decimal("5.00")
        currency = "EUR"

    class _Tx:
        def __init__(self, data: dict[str, Any]) -> None:
            self.data = data

    out = mt940_parse.lines_from_mt940_transactions([_Tx({}), _Tx({"amount": _Amt()})])
    assert len(out) == 1  # the parser skips the transaction without an amount


def test_find_local_none() -> None:
    assert camt_parse._find_local(None, "X") is None


def test_camt_date_invalid_calendar_date() -> None:
    # Length of 10 or more, but not a valid date → the ValueError branch.
    el = ET.fromstring("<ValDt><Dt>2024-13-45</Dt></ValDt>")
    assert camt_parse._camt_date(el) is None


def test_decode_latin1_fallback() -> None:
    # 0xFF is not valid UTF-8, so the latin-1 fallback applies.
    assert "ÿ" in statement.decode_bytes(b"\xff")


def test_camt_skips_entries_without_usable_amount() -> None:
    xml = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><Stmt>
 <Ntry><CdtDbtInd>CRDT</CdtDbtInd></Ntry>
 <Ntry><Amt Ccy="EUR">nope</Amt><CdtDbtInd>CRDT</CdtDbtInd></Ntry>
</Stmt></Document>"""
    with pytest.raises(statement.StatementParseError):
        camt_parse.parse_camt(xml)


def test_parse_statement_mt940_without_filename() -> None:
    mt = (
        b":20:X\n:25:1/2\n:60F:C240101EUR0,00\n"
        b":61:2401010101CR1,00NTRFNONREF\n:86:051?20Test\n:62F:C240101EUR1,00\n-"
    )
    lines = statement.parse_statement(mt)
    assert lines and lines[0].amount == Decimal("1.00")


# service branches
def _svc(session: _Session, monkeypatch: pytest.MonkeyPatch) -> BankService:
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(service_base, "audit_record", _noop)
    # Disable the SSRF revalidation (DNS) in the unit test. A separate test covers it.
    monkeypatch.setattr(fc, "validate_fints_endpoint", lambda _u: None)
    settings = load_settings(fints_enc_key=_KEY)
    return BankService(session, settings=settings, actor="t", principal_id=_PID)  # type: ignore[arg-type]


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
    line = statement.StatementLine(
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
    session.execute_q.append(_Result([]))  # no booking candidates
    session.scalar_q.append(mem_budget)  # counterparty IBAN memory
    line = statement.StatementLine(amount=Decimal("10.00"), counterparty_iban="DEXP")
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
    line = _line(amount=Decimal("-9.00"))  # kind expense, no suggested budget
    session.scalar_q.append(1)  # count
    session.scalars_q.append(_Result([line]))
    page = await svc.list_lines_paged(account_id=uuid.uuid4(), state="unmatched")
    assert len(page.items) == 1
    assert page.items[0].kind == "expense"
    assert page.items[0].suggested_path_key is None


@pytest.mark.asyncio
async def test_list_lines_matched_expense_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fill `matchedExpenseId` from `bank_allocation` for a matched line.

    On a split, the oldest allocation wins. An open line keeps no expense id
    (#expenses-ux2).
    """
    session = _Session()
    svc = _svc(session, monkeypatch)
    open_line = _line(amount=Decimal("-9.00"))
    matched = _line(amount=Decimal("-20.00"), match_state="matched")
    exp_a, exp_b = uuid.uuid4(), uuid.uuid4()
    session.scalar_q.append(2)  # count
    session.scalars_q.append(_Result([open_line, matched]))
    # Allocations sorted by created_at: setdefault keeps the first one.
    session.execute_q.append(_Result([(matched.id, exp_a), (matched.id, exp_b)]))
    page = await svc.list_lines_paged(account_id=uuid.uuid4(), state=None)
    by_id = {item.id: item for item in page.items}
    assert by_id[matched.id].matched_expense_id == exp_a
    assert by_id[open_line.id].matched_expense_id is None


@pytest.mark.asyncio
async def test_confirm_line_description_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    from app.modules.budget.tree.service import BudgetTreeService
    from app.modules.budget.tree_schemas import ConfirmLineRequest, ExpenseOut

    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line()
    session.put(line)
    seen: dict[str, Any] = {}

    async def _book(
        self: Any, payload: Any, *, actor: str, commit: bool = True, account_id: Any = None
    ) -> ExpenseOut:
        seen["description"] = payload.description
        return ExpenseOut(
            id=uuid.uuid4(), budgetId=uuid.uuid4(), fiscalYearId=uuid.uuid4(),
            kind="expense", amount=Decimal("50.00"), currency="EUR",
            description=payload.description, createdAt=datetime(2024, 1, 1, tzinfo=UTC),
        )

    monkeypatch.setattr(BudgetTreeService, "book_expense", _book)
    # The claim wins. Without a counterparty_iban there is no _remember_counterparty.
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
    from app.modules.budget.bank import client as fc

    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = _account()
    session.put(acc)

    def _start(creds: Any, *, start_date: Any) -> fc.FintsOutcome:
        return fc.FintsOutcome(status="done", new_state=None, lines=[])

    monkeypatch.setattr(fc, "start_sync", _start)
    session.scalar_q.append(_cred(account_id=acc.id))  # _load_credential
    session.execute_q.append(_Result([]))  # _purge_expired_sessions
    res = await svc.sync_account(acc.id)
    assert res.status == "done"
    assert res.imported == 0


@pytest.mark.asyncio
async def test_submit_tan_still_needs_tan(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.budget.bank import client as fc

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
    payload = session.added[-1].payload_encrypted
    session.scalar_q.append(_cred(account_id=acc.id))  # _load_credential
    future = datetime.now(UTC) + timedelta(seconds=60)
    session.execute_q.append(_Result([(payload, future)]))  # _claim_session

    def _submit(creds: Any, pending: Any, tan: str) -> fc.FintsOutcome:
        return fc.FintsOutcome(
            status="needs_tan", tan_mechanism="962", client_data=b"c", dialog_data=b"d",
            tan_data=b"t", decoupled=True,
        )

    monkeypatch.setattr(fc, "submit_tan", _submit)
    res = await svc.submit_tan(acc.id, token, "")
    assert res.status == "needs_tan"
    # The token rotates: the old one is used up (anti-replay), the new one is fresh.
    assert res.session_token is not None
    assert res.session_token != token


def test_matcher_far_date_branch() -> None:
    from app.modules.budget.bank import match as bm

    cand = bm.ExpenseCandidate(
        expense_id="e", budget_id="b", amount=Decimal("50.00"), when=date(2023, 1, 1),
        reference=None,
    )
    r = bm.score_candidate(
        line_amount=Decimal("-50.00"), line_when=date(2024, 6, 1),
        line_ref=None, line_e2e=None, candidate=cand,
    )
    assert "entfernt" in r.reason  # the branch above _WIDE_DAYS


def test_matcher_wide_window_branch() -> None:
    from app.modules.budget.bank import match as bm

    # A delta of 4 days sits between _TIGHT_DAYS(2) and _WIDE_DAYS(5) → middle date score.
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
async def test_claim_session_missing_or_wrong_account(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    # `DELETE ... WHERE id AND account_id RETURNING` returns nothing. An unknown token
    # and an account mismatch both fail the WHERE clause, so the service raises
    # NotFoundError.
    with pytest.raises(NotFoundError):
        await svc._claim_session(uuid.uuid4(), uuid.uuid4())


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
    session.scalar_q.append(_cred(account_id=acc.id))  # _load_credential
    session.execute_q.append(_Result([]))  # _purge_expired_sessions
    with pytest.raises(ServiceUnavailableError):
        await svc.sync_account(acc.id)


@pytest.mark.asyncio
async def test_sync_account_bank_locked_sets_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set 409 fints_bank_locked plus a credential cooldown on a bank lock (#fints-review)."""
    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = _account()
    session.put(acc)

    def _locked(creds: Any, *, start_date: Any) -> Any:
        raise fc.FintsBankLockedError("locked")

    monkeypatch.setattr(fc, "start_sync", _locked)
    cred = _cred(account_id=acc.id)
    session.scalar_q.append(cred)  # _load_credential
    session.execute_q.append(_Result([]))  # _purge_expired_sessions
    with pytest.raises(ConflictError) as ei:
        await svc.sync_account(acc.id)
    assert ei.value.code == "fints_bank_locked"
    assert cred.fints_locked_until is not None  # cooldown set ...
    assert session.commits >= 1  # ... and persisted


@pytest.mark.asyncio
async def test_sync_account_auth_rejected_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """Map a signature or PIN rejection to 409 fints_auth_rejected, not to a 503."""
    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = _account()
    session.put(acc)

    def _rejected(creds: Any, *, start_date: Any) -> Any:
        raise fc.FintsAuthRejectedError("rejected")

    monkeypatch.setattr(fc, "start_sync", _rejected)
    session.scalar_q.append(_cred(account_id=acc.id))
    session.execute_q.append(_Result([]))
    with pytest.raises(ConflictError) as ei:
        await svc.sync_account(acc.id)
    assert ei.value.code == "fints_auth_rejected"


@pytest.mark.asyncio
async def test_sync_account_blocked_while_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    """A credential that is already locked gives 409 with NO network call (anti-hammer)."""
    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = _account()
    session.put(acc)
    calls = {"n": 0}

    def _must_not_run(creds: Any, *, start_date: Any) -> Any:
        calls["n"] += 1
        raise AssertionError("network must not be hit while locked")

    monkeypatch.setattr(fc, "start_sync", _must_not_run)
    cred = _cred(account_id=acc.id)
    cred.fints_locked_until = datetime.now(UTC) + timedelta(minutes=10)
    session.scalar_q.append(cred)  # _load_credential
    with pytest.raises(ConflictError) as ei:
        await svc.sync_account(acc.id)
    assert ei.value.code == "fints_bank_locked"
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_sync_account_expired_lock_allows_and_clears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An expired cooldown does not block. A good sync clears it (#fints-review)."""
    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = _account()
    session.put(acc)

    def _done(creds: Any, *, start_date: Any) -> Any:
        return fc.FintsOutcome(status="done", lines=[], new_state=b"st")

    monkeypatch.setattr(fc, "start_sync", _done)
    cred = _cred(account_id=acc.id)
    cred.fints_locked_until = datetime.now(UTC) - timedelta(minutes=1)  # expired
    session.scalar_q.append(cred)  # _load_credential
    session.execute_q.append(_Result([]))  # _purge_expired_sessions
    res = await svc.sync_account(acc.id)
    assert res.status == "done"
    assert cred.fints_locked_until is None  # cleared


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
    payload = session.added[-1].payload_encrypted
    session.scalar_q.append(_cred(account_id=acc.id))  # _load_credential
    future = datetime.now(UTC) + timedelta(seconds=60)
    session.execute_q.append(_Result([(payload, future)]))  # _claim_session

    def _boom(creds: Any, pending: Any, tan: str) -> Any:
        raise fc.FintsError("nope")

    monkeypatch.setattr(fc, "submit_tan", _boom)
    with pytest.raises(ServiceUnavailableError):
        await svc.submit_tan(acc.id, token, "123456")


@pytest.mark.asyncio
async def test_submit_tan_bank_locked_sets_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bank lock during the TAN submit gives 409 plus a cooldown (#fints-review)."""
    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = _account()
    session.put(acc)
    token = uuid.uuid4()
    out = fc.FintsOutcome(
        status="needs_tan", tan_mechanism="962", client_data=b"c", dialog_data=b"d", tan_data=b"t",
    )
    await svc._store_session(acc.id, out, token=token)
    payload = session.added[-1].payload_encrypted
    cred = _cred(account_id=acc.id)
    session.scalar_q.append(cred)  # _load_credential
    future = datetime.now(UTC) + timedelta(seconds=60)
    session.execute_q.append(_Result([(payload, future)]))  # _claim_session

    def _locked(creds: Any, pending: Any, tan: str) -> Any:
        raise fc.FintsBankLockedError("locked")

    monkeypatch.setattr(fc, "submit_tan", _locked)
    with pytest.raises(ConflictError) as ei:
        await svc.submit_tan(acc.id, token, "123456")
    assert ei.value.code == "fints_bank_locked"
    assert cred.fints_locked_until is not None


@pytest.mark.asyncio
async def test_tan_session_roundtrip_preserves_login_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep `tan_for_login` through encode, store and claim (#fints login-SCA).

    Without the flag, `submit_tan` does not know that it must still fetch the
    transactions after the login TAN.
    """
    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = _account()
    token = uuid.uuid4()
    out = fc.FintsOutcome(
        status="needs_tan", tan_mechanism="962", client_data=b"c", dialog_data=b"d",
        tan_data=b"t", tan_for_login=True,
    )
    await svc._store_session(acc.id, out, token=token)
    payload = session.added[-1].payload_encrypted
    future = datetime.now(UTC) + timedelta(seconds=60)
    session.execute_q.append(_Result([(payload, future)]))  # _claim_session
    restored = await svc._claim_session(token, acc.id)
    assert restored.tan_for_login is True


@pytest.mark.asyncio
async def test_stage_lines_too_many(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(_Session(), monkeypatch)
    lines = [
        statement.StatementLine(amount=Decimal("1.00"))
        for _ in range(service_base.MAX_STATEMENT_LINES + 1)
    ]
    with pytest.raises(ValidationProblem):
        await svc._stage_lines(_account(), lines)


@pytest.mark.asyncio
async def test_stage_lines_rejects_non_eur(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(_Session(), monkeypatch)
    lines = [statement.StatementLine(amount=Decimal("1.00"), currency="USD")]
    with pytest.raises(ValidationProblem):
        await svc._stage_lines(_account(), lines)


@pytest.mark.asyncio
async def test_confirm_line_claim_lost(monkeypatch: pytest.MonkeyPatch) -> None:
    # Concurrent loser: the claim UPDATE returns 0 rows → already_matched.
    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line()
    session.put(line)
    session.execute_q.append(_Result([]))  # claim lost
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
    session.scalar_q.append(uuid.uuid4())  # already allocated
    with pytest.raises(ValidationProblem):
        await svc.confirm_line(line.id, ConfirmLineRequest(matchExpenseId=exp.id))


@pytest.mark.asyncio
async def test_confirm_line_booking_failure_reverts_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.budget.tree.service import BudgetTreeService

    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line()
    session.put(line)

    async def _boom(
        self: Any, payload: Any, *, actor: str, commit: bool = True, account_id: Any = None
    ) -> Any:
        raise RuntimeError("budget gone")

    monkeypatch.setattr(BudgetTreeService, "book_expense", _boom)
    session.execute_q.append(_Result([(line.id,)]))  # the claim wins, then booking fails
    with pytest.raises(RuntimeError):
        await svc.confirm_line(line.id, ConfirmLineRequest(budgetId=uuid.uuid4()))
    # One transaction: a single rollback undoes the claim and the booking together.
    assert getattr(session, "rollbacks", 0) == 1


@pytest.mark.asyncio
async def test_ignore_line_rejects_matched(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    line = _line(match_state="matched")
    session.put(line)
    with pytest.raises(ValidationProblem):
        await svc.ignore_line(line.id)
