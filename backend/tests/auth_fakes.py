"""Test-Fakes für DB-nahe Auth-Logik (Unit-Suite ohne Docker).

Mockt `AsyncSession.execute` über eine vorab gefüllte Ergebnis-Queue, sodass
service-/rbac-/session-Branches deterministisch und ohne echte DB geprüft werden.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class FakeResult:
    """Minimaler `Result`-Ersatz (`scalar_one_or_none` / `scalars`)."""

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
    """`AsyncSession`-Stub: `execute`/`scalars` liefern die Ergebnisse in Reihenfolge.

    `get` zieht aus einer eigenen Queue (`gets`), da `AsyncSession.get` nicht über
    `execute` läuft. Reicht für die DB-nahen Service-/RBAC-Branches ohne Docker.
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
    """`AsyncSession`-kompatibler Fake (Rückgabe `Any` → ohne Cast einsetzbar)."""
    return FakeSession(list(results), gets=gets)
