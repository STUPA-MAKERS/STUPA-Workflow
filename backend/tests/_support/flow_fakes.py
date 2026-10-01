"""Test fakes for the flow engine, for the unit suite that runs without Docker.

These fakes extend the pattern of `tests._support.auth_fakes`. A result carries a
`rowcount` for the optimistic `UPDATE ... WHERE` in `fire`. `flush` gives an id to each
new object, in place of `gen_random_uuid()` in the database. The session also counts the
`rollback` calls.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any


class FakeResult:
    """Stand-in for `Result` with an optional `rowcount` that defaults to the item count."""

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


class FakeSavepoint:
    """Stand-in for the `session.begin_nested()` context manager (a SAVEPOINT).

    The session counts the savepoints and the savepoint rollbacks. An exception in the
    block counts as a rollback and travels on, as with SQLAlchemy.
    """

    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSavepoint:
        self.session.savepoints += 1
        return self

    async def __aexit__(self, exc_type: object, _exc: object, _tb: object) -> bool:
        if exc_type is not None:
            self.session.savepoint_rollbacks += 1
        return False


class FakeSession:
    """Stub for `AsyncSession` where `execute` returns the results in order."""

    def __init__(self, results: Iterable[FakeResult] = ()) -> None:
        self._results = list(results)
        self.scalar_results: list[Any] = []
        # Separate queue for `session.get(Model, id)` in the delegation service. It is
        # independent of the `execute` order. The default `None` means not found.
        self.get_results: list[Any] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        # Recorded so a test can check a statement, for example the vote cancellation UPDATE.
        self.statements: list[Any] = []
        self.flushed = 0
        self.committed = 0
        self.rolled_back = 0
        self.savepoints = 0
        self.savepoint_rollbacks = 0

    def begin_nested(self) -> FakeSavepoint:
        """Stand-in for `session.begin_nested`. The vote close stages its branch here."""
        return FakeSavepoint(self)

    async def execute(self, stmt: Any) -> FakeResult:
        self.statements.append(stmt)
        if not self._results:
            return FakeResult()
        return self._results.pop(0)

    async def get(self, _model: Any, _ident: Any) -> Any:
        """Stand-in for `session.get` that returns the `get_results` queue in order."""
        if self.get_results:
            return self.get_results.pop(0)
        return None

    async def scalar(self, _stmt: Any) -> Any:
        """Stand-in for `session.scalar`, used for example by `_deadline_passed`.

        This method reads its own queue and defaults to `None`. The `execute` order of
        the tests stays unchanged.
        """
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
        """Stand-in for `session.refresh` that does nothing.

        After the commit the service reloads the application. It then materializes the
        deadline of the new state.
        """


def result(*items: Any, rowcount: int | None = None) -> FakeResult:
    return FakeResult(items, rowcount=rowcount)


def fake_session(*results: FakeResult) -> Any:
    """Build an `AsyncSession` compatible fake that a caller can use without a cast."""
    return FakeSession(list(results))
