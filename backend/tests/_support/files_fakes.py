"""Test-Fakes für files-Unit-Tests (kein echtes MinIO/ClamAV/Redis).

`FakeStorage` hält Objekte in-memory + protokolliert put/remove/presign; `FailingStorage`
wirft `StorageError`. `FakeScanQueue` sammelt enqueued IDs. `StubScanner` liefert ein
festes `ScanVerdict`. Die DB wird über `FakeSession` (aus `notifications_fakes`) gefaked.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.modules.files.scanner import ScanVerdict
from app.modules.files.storage import StorageError


class FakeStorage:
    """In-Memory-Object-Storage (erfüllt das ObjectStorage-Protokoll)."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_calls: list[str] = []
        self.removed: list[str] = []
        self.signed: list[str] = []

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)
        self.put_calls.append(key)

    async def get(self, key: str) -> bytes:
        return self.objects[key][0]

    async def get_stream(
        self, key: str, *, chunk_size: int = 64 * 1024
    ) -> AsyncIterator[bytes]:
        data = self.objects[key][0]

        async def _iter() -> AsyncIterator[bytes]:
            for off in range(0, len(data), chunk_size):
                yield data[off : off + chunk_size]

        return _iter()

    async def remove(self, key: str) -> None:
        self.removed.append(key)
        self.objects.pop(key, None)

    def presigned_get_url(
        self, key: str, *, expires_seconds: int, download_name: str | None = None
    ) -> str:
        self.signed.append(key)
        return f"https://minio.local/{key}?exp={expires_seconds}"


class FailingStorage(FakeStorage):
    """Storage, dessen Operationen `StorageError` werfen (Ausfall-Simulation)."""

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        raise StorageError("boom")

    async def get(self, key: str) -> bytes:
        raise StorageError("boom")

    async def get_stream(
        self, key: str, *, chunk_size: int = 64 * 1024
    ) -> AsyncIterator[bytes]:
        raise StorageError("boom")

    async def remove(self, key: str) -> None:
        raise StorageError("boom")

    def presigned_get_url(
        self, key: str, *, expires_seconds: int, download_name: str | None = None
    ) -> str:
        raise StorageError("boom")


class FakeScanQueue:
    """Sammelt enqueued Attachment-IDs."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    async def enqueue(self, attachment_id: uuid.UUID) -> None:
        self.enqueued.append(attachment_id)


class StubScanner:
    """Liefert ein festes Verdict; protokolliert die gescannten Bytes."""

    def __init__(self, verdict: ScanVerdict) -> None:
        self.verdict = verdict
        self.scanned: list[bytes] = []

    async def scan(self, data: bytes) -> ScanVerdict:
        self.scanned.append(data)
        return self.verdict


class RaisingScanner:
    """Wirft beim Scan (ScannerError-Simulation)."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def scan(self, data: bytes) -> Any:
        raise self.exc
