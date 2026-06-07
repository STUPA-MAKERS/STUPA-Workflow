"""Test-Fakes für die Webhook-Unit-Tests (kein echtes DB/Redis/Netz).

``FakeSession`` bedient die vom :class:`WebhookService` genutzten Methoden: ``add``,
``flush``, ``commit``, ``get`` (In-Memory-Store) sowie ``scalars`` (FIFO-Queue je
Query — der Test kontrolliert jede Antwort). ``FakeWebhookQueue`` sammelt enqueuete
Delivery-Ids.
"""

from __future__ import annotations

import uuid
from typing import Any


class FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class FakeSession:
    def __init__(self, *, scalars: list[list[Any]] | None = None) -> None:
        self.added: list[Any] = []
        self.committed = 0
        self.flushed = 0
        self.store: dict[uuid.UUID, Any] = {}
        self._scalars = scalars or []

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        self.store[obj.id] = obj

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def get(self, model: type, ident: uuid.UUID) -> Any:
        obj = self.store.get(ident)
        return obj if isinstance(obj, model) else None

    async def scalars(self, _stmt: Any) -> FakeResult:
        return FakeResult(self._scalars.pop(0))


class FakeWebhookQueue:
    """Sammelt enqueuete Delivery-Ids (keine Dedup — Test prüft Aufrufe direkt)."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    async def enqueue(self, delivery_id: uuid.UUID) -> None:
        self.enqueued.append(delivery_id)
