"""Test fakes for the PDF unit tests. They use no real pytex, MinIO, Redis or database.

`FakePdfSession` serves the database methods that `PdfService` and `RenderPipeline` call
(`get`, `scalar`, `add`, `flush`, `commit`) from an in-memory store. `FakeSessionmaker`
hands that session out as an async context manager. `FakePytex` returns fixed results or
raises a configured error. `FakeRenderQueue` collects the enqueued job ids.
"""

from __future__ import annotations

import uuid
from typing import Any


class FakePdfSession:
    """In-memory session. `get` reads the store and `scalar` pops a queue."""

    def __init__(
        self,
        *,
        store: dict[uuid.UUID, Any] | None = None,
        scalar: list[Any] | None = None,
    ) -> None:
        self.store: dict[uuid.UUID, Any] = store or {}
        self._scalar = scalar or []
        self.added: list[Any] = []
        self.committed = 0
        self.flushed = 0

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        self.store[obj.id] = obj

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def get(self, _model: type, ident: uuid.UUID) -> Any:
        return self.store.get(ident)

    async def scalar(self, _stmt: Any) -> Any:
        return self._scalar.pop(0) if self._scalar else None


class FakeSessionmaker:
    """Callable async context manager that always returns the same session."""

    def __init__(self, session: FakePdfSession) -> None:
        self.session = session

    def __call__(self) -> FakeSessionmaker:
        return self

    async def __aenter__(self) -> FakePdfSession:
        return self.session

    async def __aexit__(self, *_exc: object) -> None:
        return None


class FakePytex:
    """Fake pytex client. It returns fixed PDF bytes or raises a given error."""

    def __init__(self, *, pdf: bytes = b"%PDF-1.4 fake", error: Exception | None = None) -> None:
        self.pdf = pdf
        self.error = error
        self.calls: list[tuple[str, str | None]] = []
        # The `trust_level` override recorded for each call. `None` means the client
        # falls back to `trusted`. The protocol path keeps that fallback. The RCE
        # protection lives in the sanitizer, not in the trust level.
        self.trust_levels: list[str | None] = []

    async def render_pdf(
        self,
        markdown: str,
        *,
        variant: str | None = None,
        trust_level: str | None = None,
    ) -> bytes:
        self.calls.append((markdown, variant))
        self.trust_levels.append(trust_level)
        if self.error is not None:
            raise self.error
        return self.pdf


class FakeRenderQueue:
    """Collects the enqueued job ids."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    async def enqueue(self, job_id: uuid.UUID) -> None:
        self.enqueued.append(job_id)
