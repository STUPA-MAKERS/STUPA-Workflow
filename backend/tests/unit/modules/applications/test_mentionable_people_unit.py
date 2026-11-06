"""``mentionable_people``: the readers of the internal comments, without a database."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.applications import mentions as mod

APP = uuid.UUID(int=10)
GREMIUM = uuid.UUID(int=20)
ADA, BOB, EVE, ZED, GONE = (uuid.UUID(int=n) for n in (1, 2, 3, 4, 5))


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Session:
    def __init__(self, *, scalar: list[Any] | None = None, execute: list[Any] | None = None):
        self.scalar_q = list(scalar or [])
        self.execute_q = list(execute or [])

    async def scalar(self, _stmt: Any) -> Any:
        return self.scalar_q.pop(0)

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self.execute_q.pop(0))


@pytest.fixture
def holders(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, uuid.UUID | None], list[Any]]:
    """The answers of ``permission_holders`` by (permission, principal filter)."""
    table: dict[tuple[str, uuid.UUID | None], list[Any]] = {}

    async def _holders(_s: Any, perm: str, *, principal_id: uuid.UUID | None = None) -> list[Any]:
        return table.get((perm, principal_id), [])

    monkeypatch.setattr(mod, "permission_holders", _holders)
    return table


def _gremien(monkeypatch: pytest.MonkeyPatch, ids: set[uuid.UUID]) -> None:
    async def _ids(_s: Any, _app: uuid.UUID) -> set[uuid.UUID]:
        return ids

    monkeypatch.setattr(mod, "committee_gremium_ids", _ids)


async def test_readers_members_and_a_member_creator_sorted_by_name(
    monkeypatch: pytest.MonkeyPatch, holders: dict[tuple[str, uuid.UUID | None], list[Any]]
) -> None:
    holders[("application.read", None)] = [(BOB, "bob", None), (GONE, None, None)]
    holders[("application.read_all", None)] = [(ADA, None, "Ada@example.org")]
    holders[("application.transition", ZED)] = [(ZED, "Zed", None)]
    _gremien(monkeypatch, {GREMIUM})
    session = _Session(
        scalar=["creator-sub", ZED],
        execute=[[(EVE, "Eve", None), (BOB, "Bob B.", None)]],
    )
    people = await mod.mentionable_people(session, APP)  # type: ignore[arg-type]
    assert [(p.principal_id, p.display_name) for p in people] == [
        (ADA, "Ada@example.org"),
        (BOB, "Bob B."),
        (EVE, "Eve"),
        (ZED, "Zed"),
    ]


async def test_a_creator_without_a_member_right_reads_as_applicant(
    monkeypatch: pytest.MonkeyPatch, holders: dict[tuple[str, uuid.UUID | None], list[Any]]
) -> None:
    del holders
    _gremien(monkeypatch, set())
    session = _Session(scalar=["creator-sub", ZED])
    assert await mod.mentionable_ids(session, APP) == set()  # type: ignore[arg-type]


@pytest.mark.parametrize("answers", [[None], ["creator-sub", None]])
async def test_no_creator_or_no_account(
    monkeypatch: pytest.MonkeyPatch,
    holders: dict[tuple[str, uuid.UUID | None], list[Any]],
    answers: list[Any],
) -> None:
    holders[("application.read", None)] = [(ADA, "Ada", None)]
    _gremien(monkeypatch, set())
    session = _Session(scalar=answers)
    assert await mod.mentionable_ids(session, APP) == {ADA}  # type: ignore[arg-type]
