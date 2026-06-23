"""FinTS-Konto-Konfiguration (#fints): tree_service-Zweige + Schema-Validatoren.

Deckt die durch den Bankabgleich neu hinzugekommenen Branches der kritischen
Budget-Module (100 %-Branch-Gate) ab — DB-lose Fake-Session, Audit gemockt. Login/PIN
liegen seit #fints-percred je Principal getrennt (siehe ``test_bank_service``); hier bleibt
nur die **Bank-Verbindung** (Endpunkt + BLZ) am Konto."""

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
from app.shared.errors import NotFoundError, ValidationProblem

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


# --------------------------------------------------------------- create_account
@pytest.mark.asyncio
async def test_create_account_with_fints_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    # SSRF-Validator (DNS) ist separat getestet; hier neutralisieren, kein Netz im Unit-Test.
    monkeypatch.setattr(ts_mod, "validate_fints_endpoint", lambda _u: None)
    out = await svc.create_account(
        AccountCreate(
            name="Giro",
            iban="DE1",
            fintsEndpoint="https://fints.example/",
            fintsBlz="12345678",
        )
    )
    # Endpunkt + BLZ → FinTS-fähig (persönliche Logins kommen je Bucher dazu).
    assert out.fints_configured is True
    acc = next(o for o in session.added if isinstance(o, Account))
    assert acc.fints_endpoint == "https://fints.example/"
    assert acc.fints_blz == "12345678"


@pytest.mark.asyncio
async def test_create_account_without_fints(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    out = await svc.create_account(AccountCreate(name="Bar"))
    assert out.fints_configured is False
    acc = next(o for o in session.added if isinstance(o, Account))
    assert acc.fints_endpoint is None


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
async def test_update_account_connection_resets_states(monkeypatch: pytest.MonkeyPatch) -> None:
    """Geänderte Bank-Verbindung → alle hinterlegten SCA-Zustände werden verworfen."""
    session = _Session()
    svc = _svc(session, monkeypatch)
    monkeypatch.setattr(ts_mod, "validate_fints_endpoint", lambda _u: None)  # kein DNS im Unit-Test
    acc = Account(id=uuid.uuid4(), name="Giro", iban="DE1", active=True)
    session.put(acc)
    captured: dict[str, Any] = {}

    async def _reset(_self: Any, account_id: uuid.UUID) -> None:
        captured["account_id"] = account_id

    monkeypatch.setattr(BudgetTreeService, "_reset_fints_states", _reset)
    await svc.update_account(
        acc.id, AccountUpdate(fintsEndpoint="https://x/", fintsBlz="123")
    )
    assert acc.fints_endpoint == "https://x/"
    assert captured["account_id"] == acc.id


@pytest.mark.asyncio
async def test_reset_fints_states_issues_update(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_reset_fints_states`` setzt den Zustand aller Credentials des Kontos auf NULL."""
    session = _Session()
    svc = _svc(session, monkeypatch)
    seen: list[Any] = []
    original = session.execute

    async def _spy(stmt: Any) -> Any:
        seen.append(stmt)
        return await original(stmt)

    monkeypatch.setattr(session, "execute", _spy)
    await svc._reset_fints_states(uuid.uuid4())
    # ein UPDATE gegen account_fints_credential wurde abgesetzt (Aufrufer committet).
    assert seen and "account_fints_credential" in str(seen[0]).lower()


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
