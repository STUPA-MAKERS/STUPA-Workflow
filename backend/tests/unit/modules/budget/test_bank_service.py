"""BankService (#fints): Staging, Abgleich, Sync/TAN, Datei-Import — Fake-Session.

Reine Unit-Tests: die DB-Session ist ein Stub (FIFO-Queues), die Kollaborateure
(``fints_client``, ``parse_statement``, ``BudgetTreeService.book_expense``, ``audit_record``)
werden gemockt. Der FinTS-Netzpfad selbst ist ``pragma: no cover`` (kein Bank-Zugang)."""

from __future__ import annotations

import uuid
from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.modules.budget import bank_import, bank_service
from app.modules.budget import fints_client as fc
from app.modules.budget.bank_service import BankService
from app.modules.budget.tree_models import Account, BankStatementLine, BudgetExpense
from app.modules.budget.tree_schemas import ConfirmLineRequest, ExpenseOut
from app.modules.budget.tree_service import BudgetTreeService
from app.settings import load_settings
from app.shared.crypto import encrypt_secret
from app.shared.errors import NotFoundError, ServiceUnavailableError, ValidationProblem

_KEY = "0123456789abcdef-fints-enc-key"


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    """AsyncSession-Stub: ``get`` aus einem Store, ``execute``/``scalars``/``scalar`` FIFO."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, Any], Any] = {}
        self.added: list[Any] = []
        self.execute_q: deque[_Result] = deque()
        self.scalars_q: deque[_Result] = deque()
        self.scalar_q: deque[Any] = deque()
        self.commits = 0

    def put(self, obj: Any) -> None:
        self.store[(type(obj).__name__, obj.id)] = obj

    async def get(self, model: type, ident: Any) -> Any:
        return self.store.get((model.__name__, ident))

    async def execute(self, _stmt: Any) -> _Result:
        return self.execute_q.popleft() if self.execute_q else _Result([])

    async def scalars(self, _stmt: Any) -> _Result:
        return self.scalars_q.popleft() if self.scalars_q else _Result([])

    async def scalar(self, _stmt: Any) -> Any:
        return self.scalar_q.popleft() if self.scalar_q else None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


def _settings(**over: Any) -> Any:
    return load_settings(fints_enc_key=_KEY, **over)


def _service(session: _Session, monkeypatch: pytest.MonkeyPatch, **over: Any) -> BankService:
    # Audit entkoppeln (Hash-Kette würde sonst die Session anfassen).
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(bank_service, "audit_record", _noop)
    return BankService(session, settings=_settings(**over), actor="tester")  # type: ignore[arg-type]


def _account(*, configured: bool = True) -> Account:
    acc = Account(id=uuid.uuid4(), name="Giro", iban="DE111", active=True)
    if configured:
        acc.fints_endpoint = "https://fints.sparkasse.example/"
        acc.fints_blz = "12345678"
        acc.fints_login = "user1"
        acc.fints_pin_encrypted = encrypt_secret("1234", key=_KEY)
    return acc


def _line(**over: Any) -> BankStatementLine:
    base: dict[str, Any] = dict(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        idempotency_key="k",
        amount=Decimal("-50.00"),
        currency="EUR",
        match_state="unmatched",
    )
    base.update(over)
    line = BankStatementLine(**base)
    line.created_at = datetime(2024, 1, 2, tzinfo=UTC)  # CreatedAtMixin-Default fehlt ohne DB
    return line


# --------------------------------------------------------------- feature gate
def test_require_enabled_off_raises() -> None:
    svc = BankService(_Session(), settings=load_settings())  # type: ignore[arg-type]
    with pytest.raises(ServiceUnavailableError):
        svc._require_enabled()


@pytest.mark.asyncio
async def test_account_or_404(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_Session(), monkeypatch)
    with pytest.raises(NotFoundError):
        await svc._account_or_404(uuid.uuid4())


# --------------------------------------------------------------- credentials
@pytest.mark.asyncio
async def test_credentials_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_Session(), monkeypatch)
    with pytest.raises(ValidationProblem):
        svc._credentials(_account(configured=False))


@pytest.mark.asyncio
async def test_credentials_undecryptable_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_Session(), monkeypatch)
    acc = _account()
    acc.fints_pin_encrypted = "garbage"
    with pytest.raises(ValidationProblem):
        svc._credentials(acc)


@pytest.mark.asyncio
async def test_credentials_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_Session(), monkeypatch)
    creds = svc._credentials(_account())
    assert creds.pin == "1234"
    assert creds.blz == "12345678"


# --------------------------------------------------------------- staging
@pytest.mark.asyncio
async def test_stage_lines_idempotent_count(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    lines = [
        bank_import.StatementLine(amount=Decimal("10.00"), counterparty_iban="DEXP", bank_ref="a"),
        bank_import.StatementLine(amount=Decimal("-5.00"), bank_ref="b"),
    ]
    # _suggest: keine Kandidaten (execute → leer), keine Memory (scalar → None);
    # dann pg_insert returning: erste neu (Zeile), zweite Dublette (leer).
    session.execute_q.extend([_Result([]), _Result([(uuid.uuid4(),)])])  # line1: candidates, insert
    session.scalar_q.append(None)
    session.execute_q.extend([_Result([]), _Result([])])  # line2: candidates, insert(dup)
    session.scalar_q.append(None)
    imported, dup = await svc._stage_lines(acc, lines)
    assert (imported, dup) == (1, 1)


# --------------------------------------------------------------- listing
@pytest.mark.asyncio
async def test_list_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    bid = uuid.uuid4()
    line = _line(amount=Decimal("200.00"), suggested_budget_id=bid)
    session.scalars_q.append(_Result([line]))
    session.execute_q.append(_Result([(bid, "VS-800")]))  # _path_keys
    out = await svc.list_lines(account_id=None, state=None)
    assert len(out) == 1
    assert out[0].kind == "income"
    assert out[0].suggested_path_key == "VS-800"


# --------------------------------------------------------------- ignore
@pytest.mark.asyncio
async def test_ignore_line(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    line = _line()
    session.put(line)
    await svc.ignore_line(line.id)
    assert line.match_state == "ignored"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_ignore_line_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_Session(), monkeypatch)
    with pytest.raises(NotFoundError):
        await svc.ignore_line(uuid.uuid4())


# --------------------------------------------------------------- confirm
def _canned_expense(kind: str = "expense") -> ExpenseOut:
    return ExpenseOut(
        id=uuid.uuid4(),
        budgetId=uuid.uuid4(),
        fiscalYearId=uuid.uuid4(),
        kind=kind,  # type: ignore[arg-type]
        amount=Decimal("50.00"),
        currency="EUR",
        description="x",
        createdAt=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_confirm_line_new_booking(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    line = _line(counterparty_iban="DEXP")
    session.put(line)

    async def _book(self: Any, payload: Any, *, actor: str) -> ExpenseOut:
        assert payload.kind == "expense"
        return _canned_expense("expense")

    monkeypatch.setattr(BudgetTreeService, "book_expense", _book)
    out = await svc.confirm_line(line.id, ConfirmLineRequest(budgetId=uuid.uuid4()))
    assert isinstance(out, ExpenseOut)
    assert line.match_state == "matched"
    # Allocation hinzugefügt; counterparty-memory via execute (on_conflict).
    assert any(type(o).__name__ == "BankAllocation" for o in session.added)


@pytest.mark.asyncio
async def test_confirm_line_match_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    line = _line(amount=Decimal("200.00"))  # income
    session.put(line)
    expense = BudgetExpense(
        id=uuid.uuid4(),
        budget_id=uuid.uuid4(),
        fiscal_year_id=uuid.uuid4(),
        kind="income",
        amount=Decimal("200.00"),
        currency="EUR",
        description="Beitrag",
    )
    expense.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    session.put(expense)
    out = await svc.confirm_line(line.id, ConfirmLineRequest(matchExpenseId=expense.id))
    assert out.id == expense.id
    assert line.match_state == "matched"


@pytest.mark.asyncio
async def test_confirm_line_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    # not found
    with pytest.raises(NotFoundError):
        await svc.confirm_line(uuid.uuid4(), ConfirmLineRequest(budgetId=uuid.uuid4()))
    # already matched
    matched = _line(match_state="matched")
    session.put(matched)
    with pytest.raises(ValidationProblem):
        await svc.confirm_line(matched.id, ConfirmLineRequest(budgetId=uuid.uuid4()))
    # match expense missing
    line = _line()
    session.put(line)
    with pytest.raises(NotFoundError):
        await svc.confirm_line(line.id, ConfirmLineRequest(matchExpenseId=uuid.uuid4()))
    # kind mismatch (line expense, booking income)
    line2 = _line()
    session.put(line2)
    inc = BudgetExpense(
        id=uuid.uuid4(), budget_id=uuid.uuid4(), fiscal_year_id=uuid.uuid4(),
        kind="income", amount=Decimal("50.00"), currency="EUR", description="x",
    )
    session.put(inc)
    with pytest.raises(ValidationProblem):
        await svc.confirm_line(line2.id, ConfirmLineRequest(matchExpenseId=inc.id))


def test_default_description() -> None:
    assert BankService._default_description(_line(counterparty_name="A", purpose="B")) == "A — B"
    assert BankService._default_description(_line()) == "Bankumsatz"


# --------------------------------------------------------------- file import
@pytest.mark.asyncio
async def test_import_file_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    session.put(acc)
    def _parse(data: Any, filename: Any = None) -> Any:
        return [bank_import.StatementLine(amount=Decimal("10.00"), bank_ref="a")]

    monkeypatch.setattr(bank_service.bank_import, "parse_statement", _parse)
    session.execute_q.extend([_Result([]), _Result([(uuid.uuid4(),)])])
    session.scalar_q.append(None)
    res = await svc.import_file(acc.id, b"data", filename="x.sta")
    assert res.imported == 1


@pytest.mark.asyncio
async def test_import_file_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch, attachment_max_bytes=4)
    acc = _account()
    session.put(acc)
    with pytest.raises(ValidationProblem):
        await svc.import_file(acc.id, b"too-big-payload", filename="x.sta")


@pytest.mark.asyncio
async def test_import_file_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    session.put(acc)

    def _boom(data: Any, filename: Any = None) -> Any:
        raise bank_import.StatementParseError("nope")

    monkeypatch.setattr(bank_service.bank_import, "parse_statement", _boom)
    with pytest.raises(ValidationProblem):
        await svc.import_file(acc.id, b"data", filename="x.bin")


# --------------------------------------------------------------- sync / tan
@pytest.mark.asyncio
async def test_sync_account_done(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    session.put(acc)

    def _start(creds: Any, *, start_date: Any) -> fc.FintsOutcome:
        return fc.FintsOutcome(
            status="done",
            new_state=b"state",
            tan_mechanism="962",
            lines=[bank_import.StatementLine(amount=Decimal("10.00"), bank_ref="a")],
        )

    monkeypatch.setattr(fc, "start_sync", _start)
    session.execute_q.extend([_Result([]), _Result([(uuid.uuid4(),)])])
    session.scalar_q.append(None)
    res = await svc.sync_account(acc.id)
    assert res.status == "done"
    assert res.imported == 1
    assert acc.fints_state == "state"
    assert acc.fints_last_sync_at is not None


@pytest.mark.asyncio
async def test_sync_account_needs_tan(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    session.put(acc)

    def _start(creds: Any, *, start_date: Any) -> fc.FintsOutcome:
        return fc.FintsOutcome(
            status="needs_tan",
            tan_mechanism="962",
            client_data=b"c",
            dialog_data=b"d",
            tan_data=b"t",
            challenge="Bitte TAN",
            challenge_image="data:image/png;base64,QQ==",
            decoupled=False,
        )

    monkeypatch.setattr(fc, "start_sync", _start)
    res = await svc.sync_account(acc.id)
    assert res.status == "needs_tan"
    assert res.session_token is not None
    assert res.challenge == "Bitte TAN"
    assert res.challenge_image == "data:image/png;base64,QQ=="  # photoTAN/QR durchgereicht
    # Sitzung wurde verschlüsselt gespeichert.
    assert any(type(o).__name__ == "BankSyncSession" for o in session.added)


@pytest.mark.asyncio
async def test_session_roundtrip_and_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    token = uuid.uuid4()
    out = fc.FintsOutcome(
        status="needs_tan", tan_mechanism="962", client_data=b"c", dialog_data=b"d", tan_data=b"t",
        challenge="x", decoupled=True,
    )
    await svc._store_session(uuid.uuid4(), out, token=token)
    stored = session.added[-1]
    stored.id = token
    session.put(stored)
    loaded = await svc._load_session(token, stored.account_id)
    assert loaded.client_data == b"c"
    assert loaded.decoupled is True
    # expired
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(ValidationProblem):
        await svc._load_session(token, stored.account_id)


@pytest.mark.asyncio
async def test_submit_tan_done(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
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

    def _submit(creds: Any, pending: Any, tan: str) -> fc.FintsOutcome:
        assert tan == "123456"
        return fc.FintsOutcome(status="done", new_state=b"s", lines=[])

    monkeypatch.setattr(fc, "submit_tan", _submit)
    res = await svc.submit_tan(acc.id, token, "123456")
    assert res.status == "done"
    assert res.imported == 0
