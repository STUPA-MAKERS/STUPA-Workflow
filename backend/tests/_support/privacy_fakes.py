"""Test fakes for the privacy services (unit suite without a database).

The fake session splits the session calls into named queues: `gets`, `execute`,
`scalar` and `scalars`. The GDPR services (principal erasure, erasure queue, data
export, settings) then run deterministically and without Docker. Each channel returns
its items in the order of the service calls. An empty queue returns a neutral default:
an empty result or `None`. This default fits the `audit_record` advisory lock and the
genesis row.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class FakeResult:
    """Minimal replacement for `Result` with `scalar_one_or_none`, `scalars` and `all`."""

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
    """Stub for `AsyncSession` with separate channels.

    Args:
        gets: Queue for `get(model, id)`, in call order.
        execute: Queue of results for `execute(stmt)`. The default is an empty result.
        scalar: Queue of scalars for `scalar(stmt)`. The default is `None`.
        scalars: Queue of results for `scalars(stmt)`. The default is an empty result.
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
    """Return a `FakeSession` typed as `Any`.

    The `Any` return type lets the caller pass the fake straight to a service. The type
    checker then accepts it for the `AsyncSession` parameter. This follows the pattern of
    `audit_fakes`.
    """
    return FakeSession(**channels)
