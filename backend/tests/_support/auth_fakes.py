"""Test fakes for auth logic that touches the database (unit suite without Docker).

The fakes mock `AsyncSession.execute` with a pre-filled result queue. The tests then
check the service, RBAC and session branches deterministically and without a real
database.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class FakeResult:
    """Minimal replacement for `Result` with `scalar_one_or_none` and `scalars`."""

    def __init__(self, items: Iterable[Any] = ()) -> None:
        self._items = list(items)

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any:
        return self._items[0] if self._items else None


class FakeSession:
    """Stub for `AsyncSession` that returns the queued results in order.

    `execute` and `scalars` pop from the result queue. `get` pops from a separate
    queue (`gets`), because `AsyncSession.get` does not go through `execute`. This is
    enough for the service and RBAC branches that touch the database, without Docker.
    """

    def __init__(
        self, results: Iterable[FakeResult] = (), gets: Iterable[Any] = ()
    ) -> None:
        self._results = list(results)
        self._gets = list(gets)
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.flushed = 0
        self.committed = 0

    async def execute(self, _stmt: Any) -> FakeResult:
        if not self._results:
            return FakeResult()
        return self._results.pop(0)

    async def scalars(self, _stmt: Any) -> FakeResult:
        if not self._results:
            return FakeResult()
        return self._results.pop(0)

    async def scalar(self, _stmt: Any) -> Any:
        return (await self.execute(_stmt)).scalar_one_or_none()

    async def get(self, _model: Any, _ident: Any) -> Any:
        return self._gets.pop(0) if self._gets else None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1


def result(*items: Any) -> FakeResult:
    return FakeResult(items)


def fake_session(*results: FakeResult, gets: Iterable[Any] = ()) -> Any:
    """Make a fake that is compatible with `AsyncSession`.

    The return type is `Any`, so the caller can use the fake without a cast.
    """
    return FakeSession(list(results), gets=gets)
