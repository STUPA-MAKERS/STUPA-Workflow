"""BankService (#fints): staging, matching, sync and TAN, file import with a fake session.

These are pure unit tests. The DB session is a stub with FIFO queues. The tests mock the
collaborators `fints_client`, `parse_statement`, `BudgetTreeService.book_expense` and
`audit_record`. The FinTS network path itself carries `pragma: no cover` because the test
run has no bank access.
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.modules.budget.bank import client as fc
from app.modules.budget.bank import service_base, statement
from app.modules.budget.bank.service import BankService
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_models import (
    Account,
    AccountFintsCredential,
    BankStatementLine,
    BudgetExpense,
)
from app.modules.budget.tree_schemas import (
    ConfirmLineRequest,
    ExpenseOut,
    FintsCredentialIn,
)
from app.settings import load_settings
from app.shared.crypto import decrypt_secret, encrypt_secret
from app.shared.errors import NotFoundError, ServiceUnavailableError, ValidationProblem

_KEY = "0123456789abcdef-fints-enc-key"
# Fixed booker (principal) for the per-principal credentials (#fints-percred).
_PID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


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
    """AsyncSession stub: `get` reads a store. `execute`, `scalars` and `scalar` are FIFO."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, Any], Any] = {}
        self.added: list[Any] = []
        self.execute_q: deque[_Result] = deque()
        self.scalars_q: deque[_Result] = deque()
        self.scalar_q: deque[Any] = deque()
        self.commits = 0

    def put(self, obj: Any) -> None:
        self.store[(type(obj).__name__, obj.id)] = obj

    async def get(self, model: type, ident: Any, **_kw: Any) -> Any:
        # The fake ignores `with_for_update` and similar options. It takes no real lock.
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

    async def rollback(self) -> None:
        self.rollbacks = getattr(self, "rollbacks", 0) + 1


def _settings(**over: Any) -> Any:
    return load_settings(fints_enc_key=_KEY, **over)


def _service(session: _Session, monkeypatch: pytest.MonkeyPatch, **over: Any) -> BankService:
    # Decouple the audit. The hash chain would otherwise touch the session.
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(service_base, "audit_record", _noop)
    # A separate test covers the SSRF revalidation over DNS. Neutralize it here.
    monkeypatch.setattr(fc, "validate_fints_endpoint", lambda _u: None)
    return BankService(
        session,  # type: ignore[arg-type]
        settings=_settings(**over),
        actor="tester",
        principal_id=_PID,
    )


def _account(*, configured: bool = True) -> Account:
    """Build an account with an optional FinTS connection: endpoint and BLZ (#fints-percred)."""
    acc = Account(id=uuid.uuid4(), name="Giro", iban="DE111", active=True)
    if configured:
        acc.fints_endpoint = "https://fints.sparkasse.example/"
        acc.fints_blz = "12345678"
    return acc


def _cred(
    *,
    account_id: uuid.UUID | None = None,
    login: str = "user1",
    pin: str = "1234",
    state: str | None = None,
    tan: str | None = None,
) -> AccountFintsCredential:
    """Build the personal FinTS credentials of booker `_PID` for an account (#fints-percred)."""
    return AccountFintsCredential(
        id=uuid.uuid4(),
        account_id=account_id or uuid.uuid4(),
        principal_id=_PID,
        fints_login=login,
        fints_pin_encrypted=encrypt_secret(pin, key=_KEY),
        fints_tan_mechanism=tan,
        fints_state=state,
    )


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
    line.created_at = datetime(2024, 1, 2, tzinfo=UTC)  # No DB, so CreatedAtMixin sets no default
    return line


def test_line_out_resolves_counterparty_purpose_from_raw() -> None:
    """`_line_out` reads the counterparty and the purpose from the raw payload (#fints-raw).

    Raw CAMT data without those fields falls back to the stored columns.
    """
    mt = _line(
        amount=Decimal("-10.00"), counterparty_name="STALE", counterparty_iban=None,
        purpose="stale",
        raw_payload={"applicant_name": "oikos", "applicant_iban": "DE85", "purpose": "Spende"},
    )
    out = BankService._line_out(mt, None)
    assert out.counterparty_name == "oikos"
    assert out.counterparty_iban == "DE85"
    assert out.purpose == "Spende"
    camt = _line(
        amount=Decimal("-10.00"), counterparty_name="ACME", counterparty_iban="DE99",
        purpose="Rechnung", raw_payload={"creditDebit": "DBIT"},
    )
    out2 = BankService._line_out(camt, None)
    assert out2.counterparty_name == "ACME"
    assert out2.purpose == "Rechnung"
    # The fallback also drops the "KRZL" placeholder when the raw fields stay empty.
    krzl = _line(
        amount=Decimal("-10.00"), counterparty_name="KRZL", counterparty_iban="DE79",
        purpose="DATEI-NR. 1", raw_payload={"creditDebit": "DBIT"},
    )
    assert BankService._line_out(krzl, None).counterparty_name is None


def test_require_enabled_off_raises() -> None:
    svc = BankService(_Session(), settings=load_settings())  # type: ignore[arg-type]
    with pytest.raises(ServiceUnavailableError):
        svc._require_enabled()


@pytest.mark.asyncio
async def test_account_or_404(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_Session(), monkeypatch)
    with pytest.raises(NotFoundError):
        await svc._account_or_404(uuid.uuid4())


@pytest.mark.asyncio
async def test_credentials_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    """An account without a bank connection (endpoint or BLZ) gives fints_not_configured."""
    svc = _service(_Session(), monkeypatch)
    with pytest.raises(ValidationProblem):
        svc._credentials(_account(configured=False), _cred())


@pytest.mark.asyncio
async def test_credentials_undecryptable_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_Session(), monkeypatch)
    cred = _cred()
    cred.fints_pin_encrypted = "garbage"
    with pytest.raises(ValidationProblem):
        svc._credentials(_account(), cred)


@pytest.mark.asyncio
async def test_credentials_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_Session(), monkeypatch)
    creds = svc._credentials(_account(), _cred())
    assert creds.pin == "1234"
    assert creds.blz == "12345678"
    assert creds.login == "user1"


@pytest.mark.asyncio
async def test_require_principal_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing principal id breaks an internal invariant and gives 503."""
    monkeypatch.setattr(service_base, "audit_record", lambda *_a, **_k: None)
    svc = BankService(_Session(), settings=_settings(), principal_id=None)  # type: ignore[arg-type]
    with pytest.raises(ServiceUnavailableError):
        svc._require_principal()


@pytest.mark.asyncio
async def test_load_credential_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing credential for the booker gives fints_no_credential.

    The frontend then asks the user to connect.
    """
    session = _Session()
    svc = _service(session, monkeypatch)
    session.scalar_q.append(None)
    with pytest.raises(ValidationProblem):
        await svc._load_credential(uuid.uuid4())


@pytest.mark.asyncio
async def test_set_credential_new(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    session.put(acc)
    session.scalar_q.append(None)  # no credential yet
    out = await svc.set_credential(
        acc.id, FintsCredentialIn(fintsLogin="user1", fintsPin="1234")
    )
    assert out.has_credential is True
    assert out.fints_login == "user1"
    cred = next(o for o in session.added if isinstance(o, AccountFintsCredential))
    assert decrypt_secret(cred.fints_pin_encrypted, key=_KEY) == "1234"
    assert cred.principal_id == _PID


@pytest.mark.asyncio
async def test_set_credential_existing_resets_state(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    session.put(acc)
    cred = _cred(account_id=acc.id, login="old", pin="0000", state="blob", tan="962")
    session.scalar_q.append(cred)
    out = await svc.set_credential(
        acc.id, FintsCredentialIn(fintsLogin="new", fintsPin="9999")
    )
    assert out.fints_login == "new"
    assert cred.fints_login == "new"
    assert decrypt_secret(cred.fints_pin_encrypted, key=_KEY) == "9999"
    # New credentials drop the previous SCA state and TAN mechanism.
    assert cred.fints_state is None
    assert cred.fints_tan_mechanism is None


@pytest.mark.asyncio
async def test_set_credential_account_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account(configured=False)
    session.put(acc)
    with pytest.raises(ValidationProblem):
        await svc.set_credential(acc.id, FintsCredentialIn(fintsLogin="u", fintsPin="1"))


@pytest.mark.asyncio
async def test_credential_status_with_and_without(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    session.put(acc)
    session.scalar_q.append(_cred(account_id=acc.id))
    with_cred = await svc.credential_status(acc.id)
    assert with_cred.configured is True
    assert with_cred.has_credential is True
    session.scalar_q.append(None)
    without = await svc.credential_status(acc.id)
    assert without.has_credential is False
    assert without.fints_login is None


@pytest.mark.asyncio
async def test_delete_credential_found_and_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    cred_id = uuid.uuid4()
    session.execute_q.append(_Result([(cred_id,)]))  # DELETE ... RETURNING matches
    await svc.delete_credential(uuid.uuid4())
    assert session.commits == 1
    # nothing to delete gives NotFoundError
    session.execute_q.append(_Result([]))
    with pytest.raises(NotFoundError):
        await svc.delete_credential(uuid.uuid4())


@pytest.mark.asyncio
async def test_stage_lines_idempotent_count(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    lines = [
        statement.StatementLine(amount=Decimal("10.00"), counterparty_iban="DEXP", bank_ref="a"),
        statement.StatementLine(amount=Decimal("-5.00"), bank_ref="b"),
    ]
    # _suggest finds no candidates (execute is empty) and no memory (scalar is None).
    # The pg_insert then returns a row for the first line and nothing for the duplicate.
    session.execute_q.extend([_Result([]), _Result([(uuid.uuid4(),)])])  # line1: candidates, insert
    session.scalar_q.append(None)
    session.execute_q.extend([_Result([]), _Result([])])  # line2: candidates, insert(dup)
    session.scalar_q.append(None)
    imported, dup, _superseded = await svc._stage_lines(acc, lines)
    assert (imported, dup) == (1, 1)


@pytest.mark.asyncio
async def test_list_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    bid = uuid.uuid4()
    line = _line(amount=Decimal("200.00"), suggested_budget_id=bid)
    session.scalar_q.append(1)  # count
    session.scalars_q.append(_Result([line]))
    session.execute_q.append(_Result([(bid, "VS-800")]))  # _path_keys
    page = await svc.list_lines_paged(account_id=None, state=None)
    assert page.total == 1
    assert len(page.items) == 1
    assert page.items[0].kind == "income"
    assert page.items[0].suggested_path_key == "VS-800"


@pytest.mark.asyncio
async def test_list_lines_paged_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    """The kind, q and date filters plus the amount sort cover the remaining branches."""
    session = _Session()
    svc = _service(session, monkeypatch)
    session.scalar_q.append(0)  # count
    session.scalars_q.append(_Result([]))
    page = await svc.list_lines_paged(
        account_id=uuid.uuid4(), state="unmatched", kind="expense", q="miete",
        date_from="2026-01-01", date_to="2026-12-31", sort="amount", order="asc",
        limit=10, offset=0,
    )
    assert page.total == 0
    assert page.items == []


@pytest.mark.asyncio
async def test_list_lines_paged_linked_and_income_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover the last filter branches: linked True (booked), linked False (open), kind income."""
    session = _Session()
    svc = _service(session, monkeypatch)
    for linked, kind in ((True, "income"), (False, None)):
        session.scalar_q.append(0)  # count
        session.scalars_q.append(_Result([]))
        page = await svc.list_lines_paged(account_id=None, state=None, linked=linked, kind=kind)
        assert page.total == 0
        assert page.items == []


@pytest.mark.asyncio
async def test_list_lines_paged_excludes_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """The All view (state None, include_ignored False) hides set-aside lines."""
    session = _Session()
    svc = _service(session, monkeypatch)
    session.scalar_q.append(0)  # count
    session.scalars_q.append(_Result([]))
    page = await svc.list_lines_paged(account_id=None, state=None, include_ignored=False)
    assert page.total == 0
    assert page.items == []


@pytest.mark.asyncio
async def test_get_line_includes_raw_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """The detail view returns rawPayload and idempotencyKey.

    Both fields help to diagnose the source format and the batch handling.
    """
    session = _Session()
    svc = _service(session, monkeypatch)
    raw = {"batch": "true", "batch_total": "-500.00", "purpose": "DATEI-NR. 1"}
    line = _line(idempotency_key="idem-1", raw_payload=dict(raw))
    session.put(line)
    detail = await svc.get_line(line.id)
    assert detail.raw_payload == raw
    assert detail.idempotency_key == "idem-1"
    assert detail.amount == Decimal("-50.00")
    with pytest.raises(NotFoundError):
        await svc.get_line(uuid.uuid4())


@pytest.mark.asyncio
async def test_ignore_line(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    line = _line()
    session.put(line)
    session.execute_q.append(_Result([(line.id,)]))  # the conditional claim wins
    await svc.ignore_line(line.id)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_ignore_line_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_Session(), monkeypatch)
    with pytest.raises(NotFoundError):
        await svc.ignore_line(uuid.uuid4())


@pytest.mark.asyncio
async def test_ignore_line_records_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """The optional reason reaches the audit data with the whitespace trimmed."""
    captured: list[dict[str, Any]] = []

    async def _capture(_session: Any, **kw: Any) -> None:
        captured.append(kw)

    session = _Session()
    svc = _service(session, monkeypatch)
    monkeypatch.setattr(service_base, "audit_record", _capture)
    line = _line()
    session.put(line)
    session.execute_q.append(_Result([(line.id,)]))  # claim wins
    await svc.ignore_line(line.id, reason="  Doppelbuchung  ")
    assert session.commits == 1
    assert captured and captured[0]["data"] == {"reason": "Doppelbuchung"}


@pytest.mark.asyncio
async def test_reactivate_line(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    line = _line(match_state="ignored")
    session.put(line)
    session.execute_q.append(_Result([(line.id,)]))  # claim (ignored -> unmatched) wins
    out = await svc.reactivate_line(line.id)
    assert out.match_state == "unmatched"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_reactivate_line_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_Session(), monkeypatch)
    with pytest.raises(NotFoundError):
        await svc.reactivate_line(uuid.uuid4())


@pytest.mark.asyncio
async def test_reactivate_line_rejects_non_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only an ignored line reactivates. Any other state gives 422 (line_not_ignored)."""
    session = _Session()
    svc = _service(session, monkeypatch)
    line = _line(match_state="matched")
    session.put(line)
    session.execute_q.append(_Result([]))  # claim misses because the line is not ignored
    with pytest.raises(ValidationProblem) as ei:
        await svc.reactivate_line(line.id)
    assert ei.value.code == "line_not_ignored"


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

    async def _book(
        self: Any, payload: Any, *, actor: str, commit: bool = True, account_id: Any = None
    ) -> ExpenseOut:
        assert payload.kind == "expense"
        assert commit is False  # the bank matching books in the shared transaction
        return _canned_expense("expense")

    monkeypatch.setattr(BudgetTreeService, "book_expense", _book)
    session.execute_q.extend([_Result([(line.id,)]), _Result([])])  # claim wins, remember
    out = await svc.confirm_line(line.id, ConfirmLineRequest(budgetId=uuid.uuid4()))
    assert isinstance(out, ExpenseOut)
    # The service adds the allocation. The counterparty memory goes through execute
    # with on_conflict.
    assert any(type(o).__name__ == "BankAllocation" for o in session.added)


@pytest.mark.asyncio
async def test_confirm_line_cleans_mashed_counterparty(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transaction staged before the parser fix holds the IBAN and the name in one field.

    The IBAN field itself stays empty. The booking still gets a clean correspondent, a clean
    description and a clean note (#fints).
    """
    session = _Session()
    svc = _service(session, monkeypatch)
    line = _line(
        counterparty_name="DE70120300001076878808Quentin Walz", purpose="Erstattung"
    )
    session.put(line)
    captured: dict[str, Any] = {}

    async def _book(
        self: Any, payload: Any, *, actor: str, commit: bool = True, account_id: Any = None
    ) -> ExpenseOut:
        captured["payload"] = payload
        captured["account_id"] = account_id
        return _canned_expense("expense")

    monkeypatch.setattr(BudgetTreeService, "book_expense", _book)
    session.execute_q.extend([_Result([(line.id,)]), _Result([])])  # claim, remember
    await svc.confirm_line(line.id, ConfirmLineRequest(budgetId=uuid.uuid4()))
    payload = captured["payload"]
    assert captured["account_id"] == line.account_id  # the account carries over
    assert payload.correspondent == "Quentin Walz"  # the parser splits the IBAN off
    assert payload.description == "Erstattung – Quentin Walz"
    # The note carries the name and the grouped IBAN, not the merged raw value.
    assert "Empfänger: Quentin Walz" in (payload.note or "")
    assert "DE70 1203 0000 1076 8788 08" in (payload.note or "")


@pytest.mark.asyncio
async def test_confirm_line_derives_counterparty_from_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A salary line staged before the parser fix names only "KRZL" and holds no IBAN.

    The real recipient sits in the SEPA raw fields ABWE+ and IBAN+ inside raw_payload. The
    booking gets a clean correspondent and a clean IBAN from raw_payload (#fints).
    """
    session = _Session()
    svc = _service(session, monkeypatch)
    line = _line(
        counterparty_name="KRZL",
        counterparty_iban=None,
        purpose="Gehalt 06/26",
        raw_payload={
            "applicant_name": "KRZL",
            "deviate_recipient": "Max Mustermann",
            "gvc_applicant_iban": "DE70120300001076878808",
        },
    )
    session.put(line)
    captured: dict[str, Any] = {}

    async def _book(
        self: Any, payload: Any, *, actor: str, commit: bool = True, account_id: Any = None
    ) -> ExpenseOut:
        captured["payload"] = payload
        return _canned_expense("expense")

    monkeypatch.setattr(BudgetTreeService, "book_expense", _book)
    session.execute_q.extend([_Result([(line.id,)]), _Result([])])  # claim, remember
    await svc.confirm_line(line.id, ConfirmLineRequest(budgetId=uuid.uuid4()))
    payload = captured["payload"]
    assert payload.correspondent == "Max Mustermann"  # from ABWE+, not "KRZL"
    assert "DE70 1203 0000 1076 8788 08" in (payload.note or "")  # IBAN from IBAN+


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
    session.scalar_q.append(None)  # not linked yet
    session.execute_q.append(_Result([(line.id,)]))  # claim wins
    out = await svc.confirm_line(line.id, ConfirmLineRequest(matchExpenseId=expense.id))
    assert out.id == expense.id
    assert any(type(o).__name__ == "BankAllocation" for o in session.added)


@pytest.mark.asyncio
async def test_confirm_line_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    with pytest.raises(NotFoundError):
        await svc.confirm_line(uuid.uuid4(), ConfirmLineRequest(budgetId=uuid.uuid4()))
    matched = _line(match_state="matched")
    session.put(matched)
    with pytest.raises(ValidationProblem):
        await svc.confirm_line(matched.id, ConfirmLineRequest(budgetId=uuid.uuid4()))
    line = _line()
    session.put(line)
    with pytest.raises(NotFoundError):
        await svc.confirm_line(line.id, ConfirmLineRequest(matchExpenseId=uuid.uuid4()))
    # kind mismatch: the line is an expense, the booking is an income
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
    # The short form joins purpose and name with an en dash. It falls back to the name and
    # then to a generic label. Name and purpose arrive already cleaned, with the IBAN
    # split off.
    assert BankService._default_description("A", "B") == "B – A"
    assert BankService._default_description("A", None) == "A"
    assert BankService._default_description(None, None) == "Bankumsatz"


def test_booking_note_format() -> None:
    note = BankService._booking_note(
        _line(
            purpose="AStA-Aufwandsentschädigung 03/26",
            value_date=date(2026, 4, 3),
            raw_payload={"booking_time": "09:15"},
        ),
        "expense",
        name="Quentin Walz",
        iban="DE70120300001076878808",
    )
    assert note == (
        "Empfänger: Quentin Walz\n"
        "IBAN: DE70 1203 0000 1076 8788 08\n"
        "Zweck: AStA-Aufwandsentschädigung 03/26\n"
        "Buchung: 03.04.2026, 09:15 Uhr"
    )


@pytest.mark.asyncio
async def test_import_file_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    session.put(acc)
    def _parse(data: Any, *, filename: Any = None) -> Any:
        return (
            [statement.StatementLine(amount=Decimal("10.00"), bank_ref="a")],
            statement.StatementBalance(amount=Decimal("1234.56"), as_of=date(2026, 6, 30)),
        )

    monkeypatch.setattr(statement, "parse_statement_full", _parse)
    session.execute_q.extend([_Result([]), _Result([(uuid.uuid4(),)])])
    session.scalar_q.append(None)
    res = await svc.import_file(acc.id, b"data", filename="x.sta")
    assert res.imported == 1
    # The closing balance from the file reaches the account (#fints-konten).
    assert acc.fints_last_balance == Decimal("1234.56")


def test_apply_balance() -> None:
    acc = _account()
    BankService._apply_balance(acc, None)  # no balance leaves the account unchanged
    assert acc.fints_last_balance is None
    BankService._apply_balance(
        acc, statement.StatementBalance(amount=Decimal("99.00"), as_of=date(2026, 6, 30))
    )
    assert acc.fints_last_balance == Decimal("99.00")
    assert acc.fints_balance_at is not None
    # Without a cut-off date the code uses now(), so the test checks only for a value.
    BankService._apply_balance(acc, statement.StatementBalance(amount=Decimal("5.00")))
    assert acc.fints_last_balance == Decimal("5.00")


def test_apply_balance_recency_guard() -> None:
    """The recency guard (#review) protects the newer balance.

    An older file balance does not overwrite a newer known state. A balance with the same
    cut-off date still updates the account.
    """
    acc = _account()
    BankService._apply_balance(
        acc, statement.StatementBalance(amount=Decimal("99.00"), as_of=date(2026, 6, 30))
    )
    BankService._apply_balance(
        acc, statement.StatementBalance(amount=Decimal("11.00"), as_of=date(2026, 6, 1))
    )
    assert acc.fints_last_balance == Decimal("99.00")  # the older import stays ignored
    assert acc.fints_balance_at == datetime(2026, 6, 30, tzinfo=UTC)
    # The same cut-off date still updates. The guard blocks only a strictly older state.
    BankService._apply_balance(
        acc, statement.StatementBalance(amount=Decimal("77.00"), as_of=date(2026, 6, 30))
    )
    assert acc.fints_last_balance == Decimal("77.00")


@pytest.mark.asyncio
async def test_unlink_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unlink drops the allocation and reopens the transaction. The booking stays."""
    session = _Session()
    svc = _service(session, monkeypatch)
    line = _line()
    line.match_state = "matched"
    session.put(line)
    session.execute_q.append(_Result([]))  # DELETE bank_allocation
    out = await svc.unlink_line(line.id)
    assert out.match_state == "unmatched"
    assert line.match_state == "unmatched"


@pytest.mark.asyncio
async def test_unlink_line_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_Session(), monkeypatch)
    with pytest.raises(NotFoundError):
        await svc.unlink_line(uuid.uuid4())


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
        raise statement.StatementParseError("nope")

    monkeypatch.setattr(statement, "parse_statement", _boom)
    with pytest.raises(ValidationProblem):
        await svc.import_file(acc.id, b"data", filename="x.bin")


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
            lines=[statement.StatementLine(amount=Decimal("10.00"), bank_ref="a")],
        )

    monkeypatch.setattr(fc, "start_sync", _start)
    cred = _cred(account_id=acc.id)
    session.scalar_q.append(cred)  # _load_credential
    session.execute_q.append(_Result([]))  # _purge_expired_sessions
    session.execute_q.extend([_Result([]), _Result([(uuid.uuid4(),)])])
    session.scalar_q.append(None)  # _memory_budget in _suggest
    res = await svc.sync_account(acc.id)
    assert res.status == "done"
    assert res.imported == 1
    # The encrypted fints_state sits on the credential of the booker (#fints-percred).
    # It round-trips through decrypt_secret.
    assert cred.fints_state is not None
    assert cred.fints_state != "state"
    assert decrypt_secret(cred.fints_state, key=_KEY) == "state"
    assert cred.fints_last_sync_at is not None


@pytest.mark.asyncio
async def test_sync_account_ambiguous_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ambiguous account gives 422 (fints_account_ambiguous) and sets no lock."""
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    session.put(acc)

    def _start(creds: Any, *, start_date: Any) -> fc.FintsOutcome:
        raise fc.FintsAccountSelectionError("no match")

    monkeypatch.setattr(fc, "start_sync", _start)
    cred = _cred(account_id=acc.id)
    session.scalar_q.append(cred)  # _load_credential
    session.execute_q.append(_Result([]))  # _purge_expired_sessions
    with pytest.raises(ValidationProblem) as ei:
        await svc.sync_account(acc.id)
    assert ei.value.code == "fints_account_ambiguous"
    assert cred.fints_locked_until is None  # not counted as a bank error


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
    session.scalar_q.append(_cred(account_id=acc.id))  # _load_credential
    session.execute_q.append(_Result([]))  # _purge_expired_sessions
    res = await svc.sync_account(acc.id)
    assert res.status == "needs_tan"
    assert res.session_token is not None
    assert res.challenge == "Bitte TAN"
    assert res.challenge_image == "data:image/png;base64,QQ=="  # photoTAN and QR pass through
    # The service stored the session in encrypted form.
    assert any(type(o).__name__ == "BankSyncSession" for o in session.added)


@pytest.mark.asyncio
async def test_claim_session_roundtrip_and_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    token = uuid.uuid4()
    acc_id = uuid.uuid4()
    out = fc.FintsOutcome(
        status="needs_tan", tan_mechanism="962", client_data=b"c", dialog_data=b"d", tan_data=b"t",
        challenge="x", decoupled=True, account_scope=("DE111", "97157"),
    )
    await svc._store_session(acc_id, out, token=token)
    payload = session.added[-1].payload_encrypted
    # The claim deletes atomically (DELETE ... RETURNING) and returns payload and expires_at.
    future = datetime.now(UTC) + timedelta(seconds=60)
    session.execute_q.append(_Result([(payload, future)]))
    loaded = await svc._claim_session(token, acc_id)
    assert loaded.client_data == b"c"
    assert loaded.decoupled is True
    # The account scope survives the session. The TAN resume uses it to filter the CAMT data.
    assert loaded.account_scope == ("DE111", "97157")
    # an expired session gives ValidationProblem, not 500
    past = datetime.now(UTC) - timedelta(seconds=1)
    session.execute_q.append(_Result([(payload, past)]))
    with pytest.raises(ValidationProblem):
        await svc._claim_session(token, acc_id)


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
    payload = session.added[-1].payload_encrypted
    cred = _cred(account_id=acc.id)
    session.scalar_q.append(cred)  # _load_credential
    future = datetime.now(UTC) + timedelta(seconds=60)
    session.execute_q.append(_Result([(payload, future)]))  # _claim_session

    def _submit(creds: Any, pending: Any, tan: str) -> fc.FintsOutcome:
        assert tan == "123456"
        assert pending.client_data == b"c"  # from the claimed and decrypted blob
        return fc.FintsOutcome(status="done", new_state=b"s", lines=[])

    monkeypatch.setattr(fc, "submit_tan", _submit)
    res = await svc.submit_tan(acc.id, token, "123456")
    assert res.status == "done"
    assert res.imported == 0
    # The service updated the SCA state on the credential of the booker.
    assert cred.fints_state is not None


@pytest.mark.asyncio
async def test_confirm_line_account_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A booking on another account than the transaction gives 422 (F4)."""
    session = _Session()
    svc = _service(session, monkeypatch)
    line = _line(amount=Decimal("-50.00"))
    session.put(line)
    exp = BudgetExpense(
        id=uuid.uuid4(), budget_id=uuid.uuid4(), fiscal_year_id=uuid.uuid4(),
        kind="expense", amount=Decimal("50.00"), currency="EUR", description="x",
    )
    exp.account_id = uuid.uuid4()  # differs from line.account_id
    session.put(exp)
    with pytest.raises(ValidationProblem):
        await svc.confirm_line(line.id, ConfirmLineRequest(matchExpenseId=exp.id))


@pytest.mark.asyncio
async def test_sync_account_revalidate_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SSRF revalidation at fetch time refuses. It gives 422 and makes no network call (F1)."""
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    session.put(acc)

    def _blocked(_url: str) -> None:
        raise ValueError("blocked")

    monkeypatch.setattr(fc, "validate_fints_endpoint", _blocked)
    session.scalar_q.append(_cred(account_id=acc.id))  # _load_credential
    session.execute_q.append(_Result([]))  # _purge_expired_sessions
    with pytest.raises(ValidationProblem):
        await svc.sync_account(acc.id)


@pytest.mark.asyncio
async def test_claim_session_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_Session(), monkeypatch)
    # DELETE ... RETURNING returns nothing, so the service raises NotFoundError.
    with pytest.raises(NotFoundError):
        await svc._claim_session(uuid.uuid4(), uuid.uuid4())


@pytest.mark.asyncio
async def test_claim_session_undecryptable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blob that does not decrypt after a key rotation gives 422, not 500 (Crypto #3)."""
    session = _Session()
    svc = _service(session, monkeypatch)
    future = datetime.now(UTC) + timedelta(seconds=60)
    session.execute_q.append(_Result([("not-a-fernet-token", future)]))
    with pytest.raises(ValidationProblem):
        await svc._claim_session(uuid.uuid4(), uuid.uuid4())
