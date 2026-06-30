"""BankService (#fints): Staging, Abgleich, Sync/TAN, Datei-Import — Fake-Session.

Reine Unit-Tests: die DB-Session ist ein Stub (FIFO-Queues), die Kollaborateure
(``fints_client``, ``parse_statement``, ``BudgetTreeService.book_expense``, ``audit_record``)
werden gemockt. Der FinTS-Netzpfad selbst ist ``pragma: no cover`` (kein Bank-Zugang)."""

from __future__ import annotations

import uuid
from collections import deque
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.modules.budget import bank_import, bank_service
from app.modules.budget import fints_client as fc
from app.modules.budget.bank_service import BankService
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
from app.modules.budget.tree_service import BudgetTreeService
from app.settings import load_settings
from app.shared.crypto import decrypt_secret, encrypt_secret
from app.shared.errors import NotFoundError, ServiceUnavailableError, ValidationProblem

_KEY = "0123456789abcdef-fints-enc-key"
# Fester Bucher (Principal) für die per-Principal-Zugangsdaten (#fints-percred).
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

    async def get(self, model: type, ident: Any, **_kw: Any) -> Any:
        # ``with_for_update`` u. a. werden im Fake ignoriert (keine echte Sperre).
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
    # Audit entkoppeln (Hash-Kette würde sonst die Session anfassen).
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(bank_service, "audit_record", _noop)
    # SSRF-Re-Validierung (DNS) ist separat getestet — im Unit-Test neutralisieren.
    monkeypatch.setattr(fc, "validate_fints_endpoint", lambda _u: None)
    return BankService(
        session,  # type: ignore[arg-type]
        settings=_settings(**over),
        actor="tester",
        principal_id=_PID,
    )


def _account(*, configured: bool = True) -> Account:
    """Konto mit (optionaler) FinTS-**Bank-Verbindung** — Endpunkt + BLZ (#fints-percred)."""
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
    """Persönliche FinTS-Zugangsdaten des Buchers ``_PID`` für ein Konto (#fints-percred)."""
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
    """Konto ohne Bank-Verbindung (Endpunkt/BLZ) → fints_not_configured."""
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
    """Ohne Principal-Id (interne Invariante) → 503."""
    monkeypatch.setattr(bank_service, "audit_record", lambda *_a, **_k: None)
    svc = BankService(_Session(), settings=_settings(), principal_id=None)  # type: ignore[arg-type]
    with pytest.raises(ServiceUnavailableError):
        svc._require_principal()


@pytest.mark.asyncio
async def test_load_credential_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kein Credential für den Bucher → fints_no_credential (FE fordert Verbinden)."""
    session = _Session()
    svc = _service(session, monkeypatch)
    session.scalar_q.append(None)
    with pytest.raises(ValidationProblem):
        await svc._load_credential(uuid.uuid4())


# ----------------------------------------------------- credential CRUD (#fints-percred)
@pytest.mark.asyncio
async def test_set_credential_new(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    acc = _account()
    session.put(acc)
    session.scalar_q.append(None)  # noch kein Credential
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
    # Neue Zugangsdaten → bisheriger SCA-Zustand/TAN verworfen.
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
    session.execute_q.append(_Result([(cred_id,)]))  # DELETE … RETURNING trifft
    await svc.delete_credential(uuid.uuid4())
    assert session.commits == 1
    # nichts zu löschen → NotFoundError
    session.execute_q.append(_Result([]))
    with pytest.raises(NotFoundError):
        await svc.delete_credential(uuid.uuid4())


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
    session.execute_q.append(_Result([(line.id,)]))  # konditionaler Claim gewinnt
    await svc.ignore_line(line.id)
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

    async def _book(self: Any, payload: Any, *, actor: str, commit: bool = True) -> ExpenseOut:
        assert payload.kind == "expense"
        assert commit is False  # Bankabgleich bucht in gemeinsamer Transaktion
        return _canned_expense("expense")

    monkeypatch.setattr(BudgetTreeService, "book_expense", _book)
    session.execute_q.extend([_Result([(line.id,)]), _Result([])])  # claim wins, remember
    out = await svc.confirm_line(line.id, ConfirmLineRequest(budgetId=uuid.uuid4()))
    assert isinstance(out, ExpenseOut)
    # Allocation hinzugefügt; counterparty-memory via execute (on_conflict).
    assert any(type(o).__name__ == "BankAllocation" for o in session.added)


@pytest.mark.asyncio
async def test_confirm_line_cleans_mashed_counterparty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vor dem Parser-Fix gestageter Umsatz (IBAN+Name in EINEM Feld, leeres IBAN-Feld) →
    die Buchung bekommt sauberen Empfänger/Beschreibung/Notiz (#fints)."""
    session = _Session()
    svc = _service(session, monkeypatch)
    line = _line(
        counterparty_name="DE70120300001076878808Quentin Walz", purpose="Erstattung"
    )
    session.put(line)
    captured: dict[str, Any] = {}

    async def _book(self: Any, payload: Any, *, actor: str, commit: bool = True) -> ExpenseOut:
        captured["payload"] = payload
        return _canned_expense("expense")

    monkeypatch.setattr(BudgetTreeService, "book_expense", _book)
    session.execute_q.extend([_Result([(line.id,)]), _Result([])])  # claim, remember
    await svc.confirm_line(line.id, ConfirmLineRequest(budgetId=uuid.uuid4()))
    payload = captured["payload"]
    assert payload.account_id == line.account_id  # Konto des Umsatzes übernommen
    assert payload.correspondent == "Quentin Walz"  # IBAN abgespalten
    assert payload.description == "Erstattung – Quentin Walz"
    # Notiz trägt Name + (gruppierte) IBAN, nicht den verschmolzenen Rohwert.
    assert "Empfänger: Quentin Walz" in (payload.note or "")
    assert "DE70 1203 0000 1076 8788 08" in (payload.note or "")


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
    session.scalar_q.append(None)  # noch nicht zugeordnet
    session.execute_q.append(_Result([(line.id,)]))  # claim gewinnt
    out = await svc.confirm_line(line.id, ConfirmLineRequest(matchExpenseId=expense.id))
    assert out.id == expense.id
    assert any(type(o).__name__ == "BankAllocation" for o in session.added)


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
    # Kurzform jetzt „<Zweck> – <Name>" (Gedankenstrich), Fallback Name bzw. Bankumsatz.
    # Name/Zweck kommen bereits bereinigt (IBAN abgespalten) herein.
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
    cred = _cred(account_id=acc.id)
    session.scalar_q.append(cred)  # _load_credential
    session.execute_q.append(_Result([]))  # _purge_expired_sessions
    session.execute_q.extend([_Result([]), _Result([(uuid.uuid4(),)])])
    session.scalar_q.append(None)  # _memory_budget in _suggest
    res = await svc.sync_account(acc.id)
    assert res.status == "done"
    assert res.imported == 1
    # fints_state liegt verschlüsselt am **Credential** des Buchers (#fints-percred), round-trippt.
    assert cred.fints_state is not None
    assert cred.fints_state != "state"
    assert decrypt_secret(cred.fints_state, key=_KEY) == "state"
    assert cred.fints_last_sync_at is not None


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
    assert res.challenge_image == "data:image/png;base64,QQ=="  # photoTAN/QR durchgereicht
    # Sitzung wurde verschlüsselt gespeichert.
    assert any(type(o).__name__ == "BankSyncSession" for o in session.added)


@pytest.mark.asyncio
async def test_claim_session_roundtrip_and_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _service(session, monkeypatch)
    token = uuid.uuid4()
    acc_id = uuid.uuid4()
    out = fc.FintsOutcome(
        status="needs_tan", tan_mechanism="962", client_data=b"c", dialog_data=b"d", tan_data=b"t",
        challenge="x", decoupled=True,
    )
    await svc._store_session(acc_id, out, token=token)
    payload = session.added[-1].payload_encrypted
    # Claim löscht atomar (DELETE … RETURNING) und liefert (payload, expires_at).
    future = datetime.now(UTC) + timedelta(seconds=60)
    session.execute_q.append(_Result([(payload, future)]))
    loaded = await svc._claim_session(token, acc_id)
    assert loaded.client_data == b"c"
    assert loaded.decoupled is True
    # abgelaufen → ValidationProblem (kein 500)
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
        assert pending.client_data == b"c"  # aus dem geclaimten, entschlüsselten Blob
        return fc.FintsOutcome(status="done", new_state=b"s", lines=[])

    monkeypatch.setattr(fc, "submit_tan", _submit)
    res = await svc.submit_tan(acc.id, token, "123456")
    assert res.status == "done"
    assert res.imported == 0
    # SCA-Zustand am Credential des Buchers aktualisiert.
    assert cred.fints_state is not None


# ------------------------------------------------- review round 4 (#fints-review)
@pytest.mark.asyncio
async def test_confirm_line_account_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Buchung gehört zu einem anderen Konto als der Umsatz → 422 (F4)."""
    session = _Session()
    svc = _service(session, monkeypatch)
    line = _line(amount=Decimal("-50.00"))
    session.put(line)
    exp = BudgetExpense(
        id=uuid.uuid4(), budget_id=uuid.uuid4(), fiscal_year_id=uuid.uuid4(),
        kind="expense", amount=Decimal("50.00"), currency="EUR", description="x",
    )
    exp.account_id = uuid.uuid4()  # ≠ line.account_id
    session.put(exp)
    with pytest.raises(ValidationProblem):
        await svc.confirm_line(line.id, ConfirmLineRequest(matchExpenseId=exp.id))


@pytest.mark.asyncio
async def test_sync_account_revalidate_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """SSRF-Re-Validierung zur Abruf-Zeit lehnt ab → 422, kein Netz-Call (F1)."""
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
    # DELETE … RETURNING liefert nichts → NotFoundError.
    with pytest.raises(NotFoundError):
        await svc._claim_session(uuid.uuid4(), uuid.uuid4())


@pytest.mark.asyncio
async def test_claim_session_undecryptable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nicht entschlüsselbarer Blob (Key-Rotation) → 422, nicht 500 (Crypto #3)."""
    session = _Session()
    svc = _service(session, monkeypatch)
    future = datetime.now(UTC) + timedelta(seconds=60)
    session.execute_q.append(_Result([("not-a-fernet-token", future)]))
    with pytest.raises(ValidationProblem):
        await svc._claim_session(uuid.uuid4(), uuid.uuid4())
