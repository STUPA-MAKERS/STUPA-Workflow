"""Test fakes for the files unit tests. They replace MinIO, ClamAV and Redis.

`FakeStorage` keeps the objects in memory and records the put, remove and presign calls.
`FailingStorage` raises `StorageError`. `FakeScanQueue` collects the enqueued IDs.
`StubScanner` returns a fixed `ScanVerdict`. `FakeSession` from `notifications_fakes`
fakes the database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.modules.files.scanner import ScanVerdict
from app.modules.files.storage import StorageError


class FakeStorage:
    """In-memory object storage that implements the `ObjectStorage` protocol."""

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
    """Storage that raises `StorageError` in each operation to simulate an outage."""

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
    """Collects the enqueued attachment IDs."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    async def enqueue(self, attachment_id: uuid.UUID) -> None:
        self.enqueued.append(attachment_id)


class StubScanner:
    """Scanner that returns a fixed verdict and records the scanned bytes."""

    def __init__(self, verdict: ScanVerdict) -> None:
        self.verdict = verdict
        self.scanned: list[bytes] = []

    async def scan(self, data: bytes) -> ScanVerdict:
        self.scanned.append(data)
        return self.verdict


class RaisingScanner:
    """Scanner that raises the given exception to simulate a scanner error."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def scan(self, data: bytes) -> Any:
        raise self.exc
