"""Test-Fakes für den Audit-Service (Unit-Suite ohne DB).

``execute`` liefert vorab gefüllte Ergebnisse in Reihenfolge; ``FakeResult`` deckt die
vom Service genutzten Zugriffe ab (``scalar_one``/``scalar_one_or_none``/``scalars``).
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


class FakeSession:
    def __init__(self, results: Iterable[FakeResult] = ()) -> None:
        self._results = list(results)
        self.added: list[Any] = []
        self.flushed = 0

    async def execute(self, _stmt: Any) -> FakeResult:
        if not self._results:
            return FakeResult()
        return self._results.pop(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1


def result(*items: Any) -> FakeResult:
    return FakeResult(items)


def fake_session(*results: FakeResult) -> Any:
    return FakeSession(list(results))
