"""Fixtures of the admin unit tests."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.modules.admin.service.gremien import GremiumOps


async def _no_trees(_self: GremiumOps, _gremium_id: UUID) -> None:
    """Take no tree lock: the fake sessions of these tests hold no budget table."""


@pytest.fixture(autouse=True)
def _no_budget_tree_locks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the tree locks of the Gremium delete, which have their test on Postgres."""
    monkeypatch.setattr(GremiumOps, "_lock_budget_trees", _no_trees)
