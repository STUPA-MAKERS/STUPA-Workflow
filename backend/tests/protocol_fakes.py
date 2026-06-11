"""Test-Fakes für die Protokoll-Unit-Suite (T-22, ohne DB/pytex/MinIO/Redis).

``FakeSession`` kombiniert beide vom :class:`~app.modules.protocol.service.ProtocolService`
genutzten Zugriffsmuster: ``get(model, id)`` aus einem Store + ``execute(stmt)`` aus
einer **geordneten** Ergebnis-Queue (wie :mod:`tests.flow_fakes`). ``FakeStorage``/
``FakeMailQueue`` protokollieren Put/Enqueue; ``FakePytex`` wird aus
:mod:`tests.pdf_fakes` wiederverwendet.
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
    """``get`` aus dem Store, ``execute`` aus der geordneten Queue."""

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
        self.flushed = 0
        self.committed = 0

    async def execute(self, _stmt: Any) -> FakeResult:
        # Der Header-Meta-Pfad (#protocol-metadata) fragt die Anwesenheit ab; ohne
        # positionsbasiertes Ergebnis liefern wir leer, statt einen anderen Treffer
        # zu verschieben.
        if "meeting_attendance" in str(_stmt).lower():
            return FakeResult()
        return self._results.pop(0) if self._results else FakeResult()

    async def scalars(self, _stmt: Any) -> FakeResult:
        return self._results.pop(0) if self._results else FakeResult()

    async def scalar(self, _stmt: Any) -> Any:
        """``session.scalar``-Ersatz (Protokollant-Name, Mitglieder-Count): eigene
        Queue, Default ``None`` — die ``execute``-Reihenfolge bleibt unberührt."""
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return None

    async def get(self, _model: type, ident: Any) -> Any:
        return self.store.get(ident)

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1


class FakeStorage:
    """Object-Storage-Fake: protokolliert Puts, liefert eine feste signierte URL."""

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
    """Sammelt enqueued Mails."""

    def __init__(self) -> None:
        self.sent: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.sent.append(msg)


def result(*items: Any) -> FakeResult:
    return FakeResult(items)
