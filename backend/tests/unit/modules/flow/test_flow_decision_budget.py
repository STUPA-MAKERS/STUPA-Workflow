"""The approved amount in the budget guard and the status revert (F1)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.modules.applications.decision import DecisionSwap
from app.modules.audit.models import AuditEntry
from app.modules.config_revision.revert import RevertService
from app.modules.flow.context import _budget_fits
from app.modules.flow.service import FlowService
from tests._support.auth_fakes import fake_session as auth_fake_session
from tests._support.auth_fakes import result as auth_result
from tests._support.flow_fakes import fake_session


def _app(amount: str, approved: str | None) -> Any:
    return cast(
        "Any",
        SimpleNamespace(
            budget_id=uuid.uuid4(),
            fiscal_year_id=uuid.uuid4(),
            amount=Decimal(amount),
            approved_amount=None if approved is None else Decimal(approved),
        ),
    )


async def test_budget_fits_checks_the_approved_amount() -> None:
    session = fake_session()
    session.scalar_results = [Decimal("100"), Decimal("0")]  # available = 100
    assert await _budget_fits(session, _app("150", "100")) is True


async def test_budget_fits_without_decision_checks_the_requested_amount() -> None:
    session = fake_session()
    session.scalar_results = [Decimal("100"), Decimal("0")]
    assert await _budget_fits(session, _app("150", None)) is False


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"statusEventId": "00000000-0000-0000-0000-000000000001"}, uuid.UUID(int=1)),
        ({}, None),
    ],
)
async def test_revert_status_passes_the_status_event(
    monkeypatch: pytest.MonkeyPatch, data: dict[str, str], expected: uuid.UUID | None
) -> None:
    seen: list[uuid.UUID | None] = []

    async def _revert_status(
        self: FlowService, _app_id: uuid.UUID, **kw: Any
    ) -> uuid.UUID:
        seen.append(kw["reverted_status_event_id"])
        return uuid.uuid4()

    monkeypatch.setattr(FlowService, "revert_status", _revert_status)
    app_id = uuid.uuid4()
    entry = AuditEntry(
        id=1,
        action="status_change",
        target_id=str(app_id),
        data={"fromStateId": str(uuid.uuid4()), "toStateId": str(uuid.uuid4()), **data},
    )
    out = await RevertService(auth_fake_session(auth_result(entry))).revert(1, "admin")
    assert out.entity_id == str(app_id)
    assert seen == [expected]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (
            {
                "decisionUndoneId": "00000000-0000-0000-0000-000000000001",
                "decisionRestoredId": None,
            },
            DecisionSwap(undone_id=None, restored_id=uuid.UUID(int=1)),
        ),
        (
            {
                "decisionUndoneId": "00000000-0000-0000-0000-000000000001",
                "decisionRestoredId": "00000000-0000-0000-0000-000000000002",
            },
            DecisionSwap(undone_id=uuid.UUID(int=2), restored_id=uuid.UUID(int=1)),
        ),
        ({}, None),
    ],
)
async def test_revert_status_passes_the_decision_swap_back(
    monkeypatch: pytest.MonkeyPatch, data: dict[str, Any], expected: DecisionSwap | None
) -> None:
    """A revert of a reversed entry that swapped decisions swaps them back (redo)."""
    seen: list[DecisionSwap | None] = []

    async def _revert_status(
        self: FlowService, _app_id: uuid.UUID, **kw: Any
    ) -> uuid.UUID:
        seen.append(kw["decision_swap"])
        return uuid.uuid4()

    monkeypatch.setattr(FlowService, "revert_status", _revert_status)
    entry = AuditEntry(
        id=2,
        action="status_change",
        target_id=str(uuid.uuid4()),
        data={"fromStateId": str(uuid.uuid4()), "toStateId": str(uuid.uuid4()), **data},
    )
    await RevertService(auth_fake_session(auth_result(entry))).revert(2, "admin")
    assert seen == [expected]
