"""Test fakes for the protocol unit suite (T-22, without DB, pytex, MinIO or Redis).

`FakeSession` combines the two access patterns of
`app.modules.protocol.service.ProtocolService`. It answers `get(model, id)` from a store
and `execute(stmt)` from an **ordered** result queue, as `tests._support.flow_fakes` does.
`FakeStorage` and `FakeMailQueue` record each put and each enqueue call. `FakePytex` comes
from `tests._support.pdf_fakes`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from app.modules.notifications.mail import MailMessage


class FakeResult:
    def __init__(self, items: Iterable[Any] = ()) -> None:
        self._items = list(items)

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None

    def first(self) -> Any:
        return self._items[0] if self._items else None

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._items)


class FakeSession:
    """Answer `get` from the store and `execute` from the ordered queue."""

    def __init__(
        self,
        *,
        store: dict[Any, Any] | None = None,
        results: Iterable[FakeResult] = (),
    ) -> None:
        self.store = store or {}
        self._results = list(results)
        self.scalar_results: list[Any] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.flushed = 0
        self.committed = 0

    async def execute(self, _stmt: Any) -> FakeResult:
        # The header metadata path reads the attendance. That query
        # has no entry in the ordered queue. Return an empty result for it, so that it
        # does not take the result of another query.
        if "meeting_attendance" in str(_stmt).lower():
            return FakeResult()
        return self._results.pop(0) if self._results else FakeResult()

    async def scalars(self, _stmt: Any) -> FakeResult:
        return self._results.pop(0) if self._results else FakeResult()

    async def scalar(self, _stmt: Any) -> Any:
        """Stand in for `session.scalar` (minute taker name, member count).

        This method uses its own queue and returns `None` by default. It keeps the order
        of the `execute` queue unchanged.
        """
        # The render path resolves the corporate design of the protocol. That query
        # has no entry in the queue either. Answer it with `None`, so the render
        # falls back to the variant name and the query does not eat the result of
        # another one. Same reason as the attendance case in `execute`.
        if "cd_variant" in str(_stmt).lower():
            return None
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return None

    async def get(self, _model: type, ident: Any) -> Any:
        return self.store.get(ident)

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1


class FakeStorage:
    """Object storage fake that records each put and returns a fixed signed URL."""

    def __init__(self, *, url: str = "https://minio.local/signed") -> None:
        self.url = url
        self.puts: list[tuple[str, int, str]] = []
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.puts.append((key, len(data), content_type))
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    def presigned_get_url(
        self, key: str, *, expires_seconds: int, download_name: str | None = None
    ) -> str:
        return f"{self.url}?k={key}"


class FakeMailQueue:
    """Collect the enqueued mails."""

    def __init__(self) -> None:
        self.sent: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.sent.append(msg)


def result(*items: Any) -> FakeResult:
    return FakeResult(items)
