"""Test fakes for the audit service, for the unit suite that runs without a database.

`execute` returns the prepared results in order. `FakeResult` covers the accessors that
the service uses: `scalar_one`, `scalar_one_or_none` and `scalars`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class FakeResult:
    def __init__(self, items: Iterable[Any] = ()) -> None:
        self._items = list(items)

    def scalar_one(self) -> Any:
        return self._items[0]

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._items)


class FakeAsyncScalars:
    """Async-iterable replacement for `stream_scalars`."""

    def __init__(self, items: Iterable[Any]) -> None:
        self._items = list(items)

    def __aiter__(self) -> FakeAsyncScalars:
        return self

    async def __anext__(self) -> Any:
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class FakeSession:
    def __init__(self, results: Iterable[FakeResult] = ()) -> None:
        self._results = list(results)
        self.added: list[Any] = []
        self.flushed = 0
        self.committed = 0
        self.rolled_back = 0
        self.statements: list[Any] = []

    async def execute(self, _stmt: Any) -> FakeResult:
        self.statements.append(_stmt)
        if not self._results:
            return FakeResult()
        return self._results.pop(0)

    async def stream_scalars(self, _stmt: Any) -> FakeAsyncScalars:
        items = self._results.pop(0).all() if self._results else []
        return FakeAsyncScalars(items)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


def result(*items: Any) -> FakeResult:
    return FakeResult(items)


def fake_session(*results: FakeResult) -> Any:
    return FakeSession(list(results))
