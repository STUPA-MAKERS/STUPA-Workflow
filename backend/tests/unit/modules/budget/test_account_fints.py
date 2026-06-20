"""FinTS-Konto-Konfiguration (#fints): tree_service-Zweige + Schema-Validatoren.

Deckt die durch den Bankabgleich neu hinzugekommenen Branches der kritischen
Budget-Module (100 %-Branch-Gate) ab — DB-lose Fake-Session, Audit gemockt."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.budget import tree_service as ts_mod
from app.modules.budget.tree_models import Account
from app.modules.budget.tree_schemas import (
    AccountCreate,
    AccountUpdate,
    ConfirmLineRequest,
)
from app.modules.budget.tree_service import BudgetTreeService
from app.settings import load_settings
from app.shared.crypto import decrypt_secret
from app.shared.errors import NotFoundError, ServiceUnavailableError, ValidationProblem

from .test_bank_service import _KEY, _Session


def _svc(
    session: _Session, monkeypatch: pytest.MonkeyPatch, *, key: str | None = _KEY
) -> BudgetTreeService:
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(ts_mod, "audit_record", _noop)
    settings = load_settings(fints_enc_key=key) if key else load_settings()
    return BudgetTreeService(session, settings=settings, actor="tester")  # type: ignore[arg-type]


# ----------------------------------------------------------- schema validators
def test_account_update_requires_a_field() -> None:
    with pytest.raises(ValidationError):
        AccountUpdate()


def test_confirm_line_request_validation() -> None:
    # weder budgetId noch matchExpenseId
    with pytest.raises(ValidationError):
        ConfirmLineRequest()
    # beide gesetzt → exklusiv
    with pytest.raises(ValidationError):
        ConfirmLineRequest(budgetId=uuid.uuid4(), matchExpenseId=uuid.uuid4())
    # genau eines ist ok
    assert ConfirmLineRequest(budgetId=uuid.uuid4()).budget_id is not None
    assert ConfirmLineRequest(matchExpenseId=uuid.uuid4()).match_expense_id is not None


# --------------------------------------------------------------- require key
def test_require_fints_key_raises_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(_Session(), monkeypatch, key=None)
    with pytest.raises(ServiceUnavailableError):
        svc._require_fints_key()


def test_require_fints_key_returns_key(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(_Session(), monkeypatch)
    assert svc._require_fints_key() == _KEY


# --------------------------------------------------------------- create_account
@pytest.mark.asyncio
async def test_create_account_with_fints(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    out = await svc.create_account(
        AccountCreate(
            name="Giro",
            iban="DE1",
            fintsEndpoint="https://fints.example/",
            fintsBlz="12345678",
            fintsLogin="user1",
            fintsPin="1234",
        )
    )
    assert out.fints_configured is True
    acc = next(o for o in session.added if isinstance(o, Account))
    assert acc.fints_pin_encrypted and decrypt_secret(acc.fints_pin_encrypted, key=_KEY) == "1234"
    assert acc.fints_state is None  # bei Zugangsdaten-Änderung verworfen


@pytest.mark.asyncio
async def test_create_account_without_fints(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    out = await svc.create_account(AccountCreate(name="Bar"))
    assert out.fints_configured is False
    acc = next(o for o in session.added if isinstance(o, Account))
    assert acc.fints_pin_encrypted is None


# --------------------------------------------------------------- update_account
@pytest.mark.asyncio
async def test_update_account_name_only(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = Account(id=uuid.uuid4(), name="Alt", iban="DE1", active=True)
    session.put(acc)
    out = await svc.update_account(acc.id, AccountUpdate(name="Neu"))
    assert out.name == "Neu"


@pytest.mark.asyncio
async def test_update_account_sets_then_clears_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    acc = Account(id=uuid.uuid4(), name="Giro", iban="DE1", active=True)
    session.put(acc)
    await svc.update_account(
        acc.id,
        AccountUpdate(fintsEndpoint="https://x/", fintsBlz="123", fintsLogin="u", fintsPin="9999"),
    )
    assert acc.fints_pin_encrypted is not None
    # leere PIN löscht die gespeicherte PIN (else-Zweig)
    await svc.update_account(acc.id, AccountUpdate(fintsPin=""))
    assert acc.fints_pin_encrypted is None


@pytest.mark.asyncio
async def test_update_account_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(_Session(), monkeypatch)
    with pytest.raises(NotFoundError):
        await svc.update_account(uuid.uuid4(), AccountUpdate(name="x"))


@pytest.mark.asyncio
async def test_create_account_rejects_internal_fints_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _svc(_Session(), monkeypatch)
    with pytest.raises(ValidationProblem):
        await svc.create_account(
            AccountCreate(name="Giro", fintsEndpoint="http://169.254.169.254/fints")
        )
