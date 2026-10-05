"""Shared fixtures of the delegation unit tests.

The service reads the substitute pool through `delegations.pool` (Z5). The real
helpers run a UNION of `delegation_substitute` and the faculty groups. The fake
session of these tests answers each `execute` from a queue, so the fixture puts
helpers in place that read one queued result each, as the former inline pool
queries did. `tests/unit/modules/delegations/test_pool.py` covers the real
helpers.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import literal, select

from app.modules.delegations import service as service_mod


async def _one_queued_set(session: Any, *_args: Any, **_kw: Any) -> set[UUID]:
    return set((await session.execute(select(literal(1)))).scalars().all())


async def _no_groups(*_args: Any, **_kw: Any) -> dict[UUID, dict[str, str]]:
    return {}


@pytest.fixture(autouse=True)
def _queued_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_mod, "substitutes_for", _one_queued_set)
    monkeypatch.setattr(service_mod, "substitute_gremien_for_sub", _one_queued_set)
    monkeypatch.setattr(service_mod, "group_names_for", _no_groups)
