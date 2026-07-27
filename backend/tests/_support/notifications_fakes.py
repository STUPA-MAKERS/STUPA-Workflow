"""Test fakes for the notifications unit tests.

These fakes use no real database and no real Redis. `FakeSession` serves the methods
that the service and the resolver call. It keeps `add`, `commit` and `get` on an
in-memory store. It answers `scalars` and `scalar` from prefilled FIFO queues. The test
controls every query answer.
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
        executes: list[list[Any]] | None = None,
    ) -> None:
        self.added: list[Any] = []
        self.committed = 0
        self.store: dict[uuid.UUID, Any] = {}
        self._scalars = scalars or []
        self._scalar = scalar or []
        self._executes = executes or []

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

    async def execute(self, _stmt: Any) -> FakeResult:
        """Return the next queued row result, in FIFO order.

        A row query is, for example, the `(type_id, state_id)` lookup of the dispatcher.
        The result is empty when the test queues no rows.
        """
        return FakeResult(self._executes.pop(0)) if self._executes else FakeResult([])


class FakeQueue:
    """Collect the enqueued mail messages.

    This fake does no deduplication. The test checks the calls directly.
    """

    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def enqueue(self, msg: Any) -> None:
        self.messages.append(msg)


class FakeResolver:
    """Return a fixed address list, independent of the specs and the database."""

    def __init__(self, addresses: list[str]) -> None:
        self.addresses = addresses
        self.calls: list[Any] = []

    async def resolve(
        self, specs: Any, *, application_id: Any = None, now: Any = None
    ) -> list[str]:
        self.calls.append((specs, application_id))
        return self.addresses
