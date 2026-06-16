"""Test-Fakes für pdf-Unit-Tests (kein echtes pytex/MinIO/Redis/DB).

``FakePdfSession`` bedient die vom ``PdfService``/``RenderPipeline`` genutzten
DB-Methoden (``get``/``scalar``/``add``/``flush``/``commit``) über einen In-Memory-Store;
``FakeSessionmaker`` reicht sie als async-Context-Manager. ``FakePytex`` liefert feste
Ergebnisse bzw. wirft konfigurierte Fehler; ``FakeRenderQueue`` sammelt enqueued Job-Ids.
"""

from __future__ import annotations

import uuid
from typing import Any


class FakePdfSession:
    """In-Memory-Session: ``get`` aus dem Store, ``scalar`` aus einer Queue."""

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
    """Callable → async-Context-Manager, der immer dieselbe Session liefert."""

    def __init__(self, session: FakePdfSession) -> None:
        self.session = session

    def __call__(self) -> FakeSessionmaker:
        return self

    async def __aenter__(self) -> FakePdfSession:
        return self.session

    async def __aexit__(self, *_exc: object) -> None:
        return None


class FakePytex:
    """pytex-Client-Fake: liefert feste PDF-Bytes oder wirft einen vorgegebenen Fehler."""

    def __init__(self, *, pdf: bytes = b"%PDF-1.4 fake", error: Exception | None = None) -> None:
        self.pdf = pdf
        self.error = error
        self.calls: list[tuple[str, str | None]] = []
        # Pro Aufruf mitgeschriebener ``trust_level``-Override (RCE-Schutz: der
        # Protokoll-Pfad rendert nutzer-Markdown ``untrusted``); ``None`` = Default.
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
    """Sammelt enqueued Job-Ids."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    async def enqueue(self, job_id: uuid.UUID) -> None:
        self.enqueued.append(job_id)
