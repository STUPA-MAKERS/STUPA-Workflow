"""Test fakes for the webhook unit tests.

These fakes need no real database, no Redis, and no network.

`FakeSession` supplies the methods that `WebhookService` uses: `add`, `flush`, `commit`,
`get` (an in-memory store) and `scalars`. Each `scalars` call pops the next result from a
FIFO queue, so the test controls every answer. `FakeWebhookQueue` collects the enqueued
delivery ids.
"""

from __future__ import annotations

import uuid
from typing import Any


class FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class _Nested:
    """Savepoint fake that drops each `add` made after `__aenter__` when an error occurs."""

    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.mark = 0

    async def __aenter__(self) -> _Nested:
        self.mark = len(self.session.added)
        return self

    async def __aexit__(self, exc_type: Any, *_a: Any) -> bool:
        if exc_type is not None:
            for obj in self.session.added[self.mark :]:
                oid = getattr(obj, "id", None)
                if oid is not None:
                    self.session.store.pop(oid, None)
            del self.session.added[self.mark :]
        return False  # Let the error propagate. The service catches IntegrityError.


class FakeSession:
    def __init__(
        self,
        *,
        scalars: list[list[Any]] | None = None,
        flush_errors: list[Exception | None] | None = None,
    ) -> None:
        self.added: list[Any] = []
        self.committed = 0
        self.flushed = 0
        self.store: dict[uuid.UUID, Any] = {}
        self._scalars = scalars or []
        self._flush_errors = flush_errors or []

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        self.store[obj.id] = obj

    async def flush(self) -> None:
        self.flushed += 1
        if self._flush_errors:
            err = self._flush_errors.pop(0)
            if err is not None:
                raise err

    async def commit(self) -> None:
        self.committed += 1

    def begin_nested(self) -> _Nested:
        return _Nested(self)

    async def get(self, model: type, ident: uuid.UUID) -> Any:
        obj = self.store.get(ident)
        return obj if isinstance(obj, model) else None

    async def scalars(self, _stmt: Any) -> FakeResult:
        return FakeResult(self._scalars.pop(0))


class FakeWebhookQueue:
    """Collects the enqueued delivery ids.

    This fake does not deduplicate. The test checks the calls directly.
    """

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    async def enqueue(self, delivery_id: uuid.UUID) -> None:
        self.enqueued.append(delivery_id)
