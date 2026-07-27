"""FinTS account configuration (#fints): tree/accounts branches and schema validators.

The tests cover the branches that the bank reconciliation added to the critical budget
modules (100 percent branch gate). They use a fake session without a database and a
mocked audit. Since #fints-percred, login and PIN live per principal (see
`test_bank_service`). Only the bank connection (endpoint and BLZ) stays on the account.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.budget.tree import accounts as accounts_mod
from app.modules.budget.tree import service_base as base_mod
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_models import Account
from app.modules.budget.tree_schemas import (
    AccountCreate,
    AccountUpdate,
    ConfirmLineRequest,
)
from app.settings import load_settings
from app.shared.errors import NotFoundError, ValidationProblem

from .test_bank_service import _KEY, _Session


def _svc(
    session: _Session, monkeypatch: pytest.MonkeyPatch, *, key: str | None = _KEY
) -> BudgetTreeService:
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(base_mod, "audit_record", _noop)
    settings = load_settings(fints_enc_key=key) if key else load_settings()
    return BudgetTreeService(session, settings=settings, actor="tester")  # type: ignore[arg-type]


def test_account_update_requires_a_field() -> None:
    with pytest.raises(ValidationError):
        AccountUpdate()


def test_confirm_line_request_validation() -> None:
    # neither budgetId nor matchExpenseId
    with pytest.raises(ValidationError):
        ConfirmLineRequest()
    # both set → mutually exclusive
    with pytest.raises(ValidationError):
        ConfirmLineRequest(budgetId=uuid.uuid4(), matchExpenseId=uuid.uuid4())
    # exactly one is ok
    assert ConfirmLineRequest(budgetId=uuid.uuid4()).budget_id is not None
    assert ConfirmLineRequest(matchExpenseId=uuid.uuid4()).match_expense_id is not None


@pytest.mark.asyncio
async def test_create_account_with_fints_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    svc = _svc(session, monkeypatch)
    # A separate test covers the SSRF validator, which does DNS. The unit test uses no
    # network, so it disables the validator here.
    monkeypatch.setattr(accounts_mod, "validate_fints_endpoint", lambda _u: None)
    out = await svc.create_account(
        AccountCreate(
            name="Giro",
            iban="DE1",
            fintsEndpoint="https://fints.example/",
            fintsBlz="12345678",
        )
    )
    # Endpoint plus BLZ → FinTS capable (a personal login comes per booking user).
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
    """Drop every stored SCA state when the bank connection changes."""
    session = _Session()
    svc = _svc(session, monkeypatch)
    monkeypatch.setattr(
        accounts_mod, "validate_fints_endpoint", lambda _u: None
    )  # no DNS in the unit test
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
    """Set the state of every credential of the account to NULL."""
    session = _Session()
    svc = _svc(session, monkeypatch)
    seen: list[Any] = []
    original = session.execute

    async def _spy(stmt: Any) -> Any:
        seen.append(stmt)
        return await original(stmt)

    monkeypatch.setattr(session, "execute", _spy)
    await svc._reset_fints_states(uuid.uuid4())
    # The service issued one UPDATE against account_fints_credential. The caller commits.
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
