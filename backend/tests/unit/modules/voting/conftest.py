"""Shared fixtures of the voting unit tests.

The fake sessions of these tests answer each `execute` from a queue. The pool
seat helpers of `delegations.pool_seat` read and write their own rows, so the
fixture replaces them in the voting service: no seat is free, and no seat is
freed. `tests/unit/modules/delegations/test_pool_seat.py` covers the helpers,
and the tests that need a seat replace them again.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.voting import service as voting_mod


async def _none(*_args: Any, **_kw: Any) -> None:
    return None


async def _false(*_args: Any, **_kw: Any) -> bool:
    return False


@pytest.fixture(autouse=True)
def _no_pool_seats(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(voting_mod, "claim_pool_seat", _none)
    monkeypatch.setattr(voting_mod, "pool_seat_for", _none)
    monkeypatch.setattr(voting_mod, "release_pool_seat_of", _false)
