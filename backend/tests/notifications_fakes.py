"""Test-Fakes für Notifications-Unit-Tests (kein echtes DB/Redis).

`FakeSession` bedient die vom Service/Resolver genutzten Methoden: ``add``,
``commit``, ``get`` (über einen In-Memory-Store) sowie ``scalars``/``scalar``
(über vorab gefüllte FIFO-Queues — der Test kontrolliert jede Query-Antwort).
"""

from __future__ import annotations

import uuid
from typing import Any


class FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any:
        return self._items[0] if self._items else None


class FakeSession:
    def __init__(
        self,
        *,
        scalars: list[list[Any]] | None = None,
        scalar: list[Any] | None = None,
    ) -> None:
        self.added: list[Any] = []
        self.committed = 0
        self.store: dict[uuid.UUID, Any] = {}
        self._scalars = scalars or []
        self._scalar = scalar or []

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        self.store[obj.id] = obj

    async def commit(self) -> None:
        self.committed += 1

    async def get(self, model: type, ident: uuid.UUID) -> Any:
        obj = self.store.get(ident)
        return obj if isinstance(obj, model) else None

    async def scalars(self, _stmt: Any) -> FakeResult:
        return FakeResult(self._scalars.pop(0))

    async def scalar(self, _stmt: Any) -> Any:
        return self._scalar.pop(0)


class FakeQueue:
    """Sammelt enqueued MailMessages (keine Dedup — Test prüft Aufrufe direkt)."""

    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def enqueue(self, msg: Any) -> None:
        self.messages.append(msg)


class FakeResolver:
    """Liefert feste Adressen, unabhängig von den Specs/DB."""

    def __init__(self, addresses: list[str]) -> None:
        self.addresses = addresses
        self.calls: list[Any] = []

    async def resolve(
        self, specs: Any, *, application_id: Any = None, now: Any = None
    ) -> list[str]:
        self.calls.append((specs, application_id))
        return self.addresses
