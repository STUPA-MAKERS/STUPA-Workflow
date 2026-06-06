"""Test-Fakes für die Flow-Engine (Unit-Suite ohne Docker).

Erweitert das Muster aus :mod:`tests.auth_fakes` um:

* ``rowcount`` an Ergebnissen (für das optimistische ``UPDATE … WHERE`` in ``fire``),
* ``flush`` vergibt IDs an frisch hinzugefügte Objekte (DB-``gen_random_uuid()``-Ersatz),
* ``rollback``-Zähler.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any


class FakeResult:
    """`Result`-Ersatz mit optionalem ``rowcount`` (Default: Anzahl Items)."""

    def __init__(self, items: Iterable[Any] = (), *, rowcount: int | None = None) -> None:
        self._items = list(items)
        self.rowcount = rowcount if rowcount is not None else len(self._items)

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None

    def scalar_one(self) -> Any:
        return self._items[0]

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any:
        return self._items[0] if self._items else None


class FakeSession:
    """`AsyncSession`-Stub: ``execute`` liefert die Ergebnisse in Reihenfolge."""

    def __init__(self, results: Iterable[FakeResult] = ()) -> None:
        self._results = list(results)
        self.added: list[Any] = []
        self.flushed = 0
        self.committed = 0
        self.rolled_back = 0

    async def execute(self, _stmt: Any) -> FakeResult:
        if not self._results:
            return FakeResult()
        return self._results.pop(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


def result(*items: Any, rowcount: int | None = None) -> FakeResult:
    return FakeResult(items, rowcount=rowcount)


def fake_session(*results: FakeResult) -> Any:
    """`AsyncSession`-kompatibler Fake (Rückgabe ``Any`` → ohne Cast einsetzbar)."""
    return FakeSession(list(results))
