"""Test-Fakes für die Privacy-Services (Unit-Suite ohne DB).

Trennt die Session-Zugriffe in benannte Queues (``gets``/``execute``/``scalar``/
``scalars``), damit die DSGVO-Services (Principal-Erasure, Erasure-Queue, Auskunft,
Settings) deterministisch und ohne Docker geprüft werden. Reihenfolge je Channel =
Reihenfolge der Service-Aufrufe; leere Queue liefert einen neutralen Default
(leeres Result / ``None``), passend zum ``audit_record``-Advisory-Lock + Genesis.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class FakeResult:
    """Minimaler ``Result``-Ersatz (``scalar_one_or_none``/``scalars``/``all``)."""

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
    """``AsyncSession``-Stub mit getrennten Channels.

    * ``gets``    — Queue für ``get(model, id)`` (in Reihenfolge).
    * ``execute`` — Queue für ``execute(stmt)`` → ``FakeResult`` (Default: leer).
    * ``scalar``  — Queue für ``scalar(stmt)`` → Skalar (Default: ``None``).
    * ``scalars`` — Queue für ``scalars(stmt)`` → ``FakeResult`` (Default: leer).
    """

    def __init__(
        self,
        *,
        gets: Iterable[Any] = (),
        execute: Iterable[FakeResult] = (),
        scalar: Iterable[Any] = (),
        scalars: Iterable[FakeResult] = (),
    ) -> None:
        self._gets = list(gets)
        self._execute = list(execute)
        self._scalar = list(scalar)
        self._scalars = list(scalars)
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.flushed = 0
        self.committed = 0
        self.refreshed: list[Any] = []

    async def get(self, _model: Any, _ident: Any) -> Any:
        return self._gets.pop(0) if self._gets else None

    async def execute(self, _stmt: Any) -> FakeResult:
        return self._execute.pop(0) if self._execute else FakeResult()

    async def scalar(self, _stmt: Any) -> Any:
        return self._scalar.pop(0) if self._scalar else None

    async def scalars(self, _stmt: Any) -> FakeResult:
        return self._scalars.pop(0) if self._scalars else FakeResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, obj: Any) -> None:
        self.refreshed.append(obj)


def result(*items: Any) -> FakeResult:
    return FakeResult(items)


def fake_session(**channels: Any) -> Any:
    """``FakeSession`` als ``Any`` — direkt an Services übergebbar, ohne dass der
    Typecheck den ``AsyncSession``-Parameter beanstandet (Pattern wie audit_fakes)."""
    return FakeSession(**channels)
