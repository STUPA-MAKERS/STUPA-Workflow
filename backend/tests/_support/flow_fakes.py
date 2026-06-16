"""Test-Fakes für die Flow-Engine (Unit-Suite ohne Docker).

Erweitert das Muster aus :mod:`tests._support.auth_fakes` um:

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
        self.scalar_results: list[Any] = []
        # Eigene Queue für ``session.get(Model, id)`` (Delegations-Service) —
        # unabhängig von der ``execute``-Reihenfolge. Default ``None`` (not found).
        self.get_results: list[Any] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        # Alle ``execute``-Statements (z. B. um das Vote-Storno-UPDATE zu prüfen).
        self.statements: list[Any] = []
        self.flushed = 0
        self.committed = 0
        self.rolled_back = 0

    async def execute(self, stmt: Any) -> FakeResult:
        self.statements.append(stmt)
        if not self._results:
            return FakeResult()
        return self._results.pop(0)

    async def get(self, _model: Any, _ident: Any) -> Any:
        """``session.get``-Ersatz: liefert die ``get_results``-Queue in Reihenfolge."""
        if self.get_results:
            return self.get_results.pop(0)
        return None

    async def scalar(self, _stmt: Any) -> Any:
        """``session.scalar``-Ersatz (z. B. ``_deadline_passed``): eigene Queue,
        Default ``None`` — die ``execute``-Reihenfolge der Tests bleibt unberührt."""
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flushed += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1

    async def refresh(self, _obj: Any) -> None:
        """``session.refresh``-Ersatz (No-op): nach Commit lädt der Service den Antrag
        neu, bevor er die Frist des neuen States materialisiert."""


def result(*items: Any, rowcount: int | None = None) -> FakeResult:
    return FakeResult(items, rowcount=rowcount)


def fake_session(*results: FakeResult) -> Any:
    """`AsyncSession`-kompatibler Fake (Rückgabe ``Any`` → ohne Cast einsetzbar)."""
    return FakeSession(list(results))
