"""TDD: BudgetStatsService (T-17) ohne DB — MV-Read-Mapping + Refresh, jeder Branch."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.budget.models import BudgetPot
from app.modules.budget.stats import BudgetStatsService, _as_decimal
from tests.auth_fakes import fake_session, result

_GID = uuid.uuid4()
_PID = uuid.uuid4()
_SID = uuid.uuid4()


def _pot() -> BudgetPot:
    return BudgetPot(
        id=_PID, gremium_id=_GID, name="Topf", total=Decimal("100"),
        currency="EUR", period="2026", active=True,
    )


def _usage_row(stage: str, amount: object) -> SimpleNamespace:
    return SimpleNamespace(budget_pot_id=_PID, stage=stage, total_amount=amount)


def _status_row() -> SimpleNamespace:
    return SimpleNamespace(gremium_id=_GID, current_state_id=_SID, application_count=3)


# ----------------------------------------------------------------------- refresh
@pytest.mark.parametrize("concurrently", [True, False])
async def test_refresh(concurrently: bool) -> None:
    db = fake_session()
    await BudgetStatsService(db).refresh(concurrently=concurrently)
    assert db.committed == 1


# ------------------------------------------------------------------------- usage
async def test_usage_all_filters_and_amount_coercions() -> None:
    db = fake_session(
        result(_pot()),  # pots
        result(  # mv_budget_usage rows: Decimal, None, int → _as_decimal-Branches
            _usage_row("reserved", Decimal("10")),
            _usage_row("requested", None),
            _usage_row("paid", 5),
        ),
    )
    out = await BudgetStatsService(db).usage(
        gremium_id=_GID, period="2026", budget_pot_id=_PID
    )
    assert len(out) == 1
    assert out[0].reserved == Decimal("10")
    assert out[0].paid == Decimal("5")
    assert out[0].committed == Decimal("15")


async def test_usage_no_filters_pot_without_rows() -> None:
    db = fake_session(result(_pot()), result())  # keine usage-Zeilen
    out = await BudgetStatsService(db).usage()
    assert len(out) == 1
    assert out[0].committed == Decimal("0")


# ----------------------------------------------------------- status_distribution
async def test_status_distribution_with_filter() -> None:
    db = fake_session(result(_status_row()))
    out = await BudgetStatsService(db).status_distribution(gremium_id=_GID)
    assert out[0].count == 3
    assert out[0].state_id == _SID


async def test_status_distribution_no_filter() -> None:
    db = fake_session(result())
    assert await BudgetStatsService(db).status_distribution() == []


# ------------------------------------------------------------------------- stats
async def test_stats_combines() -> None:
    db = fake_session(
        result(_pot()), result(_usage_row("paid", Decimal("7"))), result(_status_row())
    )
    out = await BudgetStatsService(db).stats()
    assert out.pots[0].paid == Decimal("7")
    assert out.status_distribution[0].count == 3


# --------------------------------------------------------------------- _as_decimal
def test_as_decimal() -> None:
    assert _as_decimal(None) == Decimal("0")
    assert _as_decimal(Decimal("3.50")) == Decimal("3.50")
    assert _as_decimal(7) == Decimal("7")
