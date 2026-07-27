"""BudgetStatsService (T-17) without a DB: the MV refresh in both branches."""

from __future__ import annotations

import pytest

from app.modules.budget.stats import BudgetStatsService
from tests._support.auth_fakes import fake_session


@pytest.mark.parametrize("concurrently", [True, False])
async def test_refresh(concurrently: bool) -> None:
    db = fake_session()
    await BudgetStatsService(db).refresh(concurrently=concurrently)
    assert db.committed == 1
