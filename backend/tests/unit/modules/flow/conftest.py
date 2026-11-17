"""Fixtures of the flow unit tests."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.modules.flow import extras_dispatcher as extras_mod

CURRENT_YEAR_ID = uuid4()


class _Years:
    """Stand-in for `BudgetTreeService` in the flow action `assignBudget`.

    The fakes of these tests hold no plan and no fiscal year table, so the stand-in gives
    the years the fake names in `active_fy`, else one year that holds every date. The
    rule itself (`choosable_years`) has its tests on Postgres.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    async def choosable_years(self, _top: Any) -> list[Any]:
        """Return the fiscal years that the fake session names."""
        fallback = [
            SimpleNamespace(id=CURRENT_YEAR_ID, start_date=date.min, end_date=date.max)
        ]
        return list(getattr(self._session, "active_fy", fallback))

    async def is_leaf(self, node: Any, fiscal_year_id: Any = None) -> bool:
        """Say the node is a leaf unless the fake session names it in `parents`."""
        return node.id not in getattr(self._session, "parents", ())

    async def takes_cost_centre(self, app: Any) -> bool:
        """Say the Antrag asks for money unless the fake session names it in `no_money`."""
        return app.id not in getattr(self._session, "no_money", ())

    async def is_income(self, node: Any, _fiscal_year_id: Any) -> bool:
        """Say the node is income when the fake session names it in `income`."""
        return node.id in getattr(self._session, "income", ())


@pytest.fixture(autouse=True)
def _choosable_years(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let `assignBudget` read the fiscal years from the fake session."""
    monkeypatch.setattr(extras_mod, "BudgetTreeService", _Years)
