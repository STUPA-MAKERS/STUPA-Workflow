"""Unit tests of the hourly draft purge (Z4) without a database.

The integration test `tests/integration/worker/test_purge_drafts.py` runs the SQL.
These tests cover the loop, the storage fallbacks and the error paths.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

import worker.files_drafts as wfd
from app.modules.files.storage import StorageError
from app.settings import load_settings

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class _Storage:
    def __init__(self, *, fail: bool = False) -> None:
        self.removed: list[str] = []
        self.fail = fail

    async def remove(self, key: str) -> None:
        if self.fail:
            raise StorageError("boom")
        self.removed.append(key)


def _batches(monkeypatch: pytest.MonkeyPatch, batches: list[tuple[int, list[str]]]) -> None:
    queue = list(batches)

    async def _batch(_maker: Any, now: datetime) -> tuple[int, list[str]]:  # noqa: ANN401
        assert now == NOW
        return queue.pop(0)

    monkeypatch.setattr(wfd, "_purge_batch", _batch)


async def test_purge_loops_until_a_short_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wfd, "PURGE_BATCH", 2)
    _batches(monkeypatch, [(2, ["a", "b"]), (2, ["c"]), (1, ["d"])])
    storage = _Storage()
    ctx = {"files_sessionmaker": object(), "object_storage": storage}
    assert await wfd.purge_draft_attachments(ctx, now=NOW) == 5
    assert storage.removed == ["a", "b", "c", "d"]


async def test_purge_with_nothing_due(monkeypatch: pytest.MonkeyPatch) -> None:
    _batches(monkeypatch, [(0, [])])
    assert await wfd.purge_draft_attachments({"files_sessionmaker": object()}, now=NOW) == 0


async def test_purge_uses_the_current_time_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[datetime] = []

    async def _batch(_maker: Any, now: datetime) -> tuple[int, list[str]]:  # noqa: ANN401
        seen.append(now)
        return 0, []

    monkeypatch.setattr(wfd, "_purge_batch", _batch)
    await wfd.purge_draft_attachments({"files_sessionmaker": object()})
    assert seen[0].tzinfo is not None


async def test_remove_objects_tolerates_errors_and_missing_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await wfd._remove_objects({"object_storage": _Storage(fail=True)}, ["a"])
    # No keys: nothing to do, not even a storage lookup.
    await wfd._remove_objects({}, [])
    # No storage in the context and none configured: the objects stay, with a warning.
    monkeypatch.setattr(wfd, "build_object_storage", lambda _settings: None)
    await wfd._remove_objects({"settings": load_settings()}, ["a"])


def test_storage_and_sessionmaker_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _Storage()
    assert wfd._storage({"object_storage": storage}) is storage
    built = _Storage()
    monkeypatch.setattr(wfd, "build_object_storage", lambda _settings: built)
    assert wfd._storage({}) is built
    assert wfd._sessionmaker({}) is not None
    sentinel = object()
    assert wfd._sessionmaker({"files_sessionmaker": sentinel}) is sentinel


class _Rows:
    def __init__(self, rows: list[Any]) -> None:  # noqa: ANN401
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Session:
    def __init__(self, rows: list[Any]) -> None:  # noqa: ANN401
        self.rows = rows
        self.statements: list[str] = []
        self.committed = 0

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def execute(self, stmt: Any) -> _Rows:  # noqa: ANN401
        self.statements.append(str(stmt))
        return _Rows(self.rows if len(self.statements) == 1 else [])

    async def commit(self) -> None:
        self.committed += 1


async def test_purge_batch_deletes_the_locked_rows() -> None:
    rows = [
        SimpleNamespace(id=uuid4(), storage_key="drafts/a/x.pdf"),
        SimpleNamespace(id=uuid4(), storage_key=None),
    ]
    session = _Session(rows)
    count, keys = await wfd._purge_batch(lambda: session, NOW)  # type: ignore[arg-type]
    assert (count, keys) == (2, ["drafts/a/x.pdf"])
    assert "FOR UPDATE" in session.statements[0]
    assert session.statements[1].startswith("DELETE FROM attachment")
    assert session.committed == 1

    empty = _Session([])
    assert await wfd._purge_batch(lambda: empty, NOW) == (0, [])  # type: ignore[arg-type]
    assert empty.committed == 0
