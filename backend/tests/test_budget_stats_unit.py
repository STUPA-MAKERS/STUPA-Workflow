"""TDD: BudgetStatsService (T-17) ohne DB — MV-Refresh, beide Branches."""

from __future__ import annotations

import pytest

from app.modules.budget.stats import BudgetStatsService
from tests.auth_fakes import fake_session


# ----------------------------------------------------------------------- refresh
@pytest.mark.parametrize("concurrently", [True, False])
async def test_refresh(concurrently: bool) -> None:
    db = fake_session()
    await BudgetStatsService(db).refresh(concurrently=concurrently)
    assert db.committed == 1
