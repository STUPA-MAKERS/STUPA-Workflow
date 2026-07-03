"""Object-storage abstraction (MinIO/S3) + signed URLs.

The service knows only the :class:`ObjectStorage` protocol — never the concrete client.
``MinioStorage`` wraps the (synchronous) ``minio`` client and hands blocking calls to a
thread pool via ``asyncio.to_thread`` (no blocking of the event loop). There is no direct
bucket access from outside.

``presigned_get_url`` returns a short-lived S3v4-signed GET URL and is used internally
(PDF module). Attachment downloads of the files API do NOT go through a signed URL but
server-side via the authz-gated ``/api/attachments/{id}/download`` route — MinIO is on
the internal Docker network without port publish, so a signed URL would be unreachable
from the browser.

``minio`` is imported lazily: without the upload path (contract CI) the lib never loads.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from app.settings import Settings

if TYPE_CHECKING:
    from minio import Minio

# Default chunk size for the streamed download: the object is read from MinIO in
# chunks, not buffered fully into memory.
STREAM_CHUNK_BYTES = 64 * 1024


class StorageError(RuntimeError):
    """Object storage unreachable / operation failed."""


class ObjectStorage(Protocol):
    """Storage interface used by the service (put/get/remove/signed URL)."""

    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def get_stream(
        self, key: str, *, chunk_size: int = STREAM_CHUNK_BYTES
    ) -> AsyncIterator[bytes]: ...

    async def remove(self, key: str) -> None: ...

    def presigned_get_url(
        self, key: str, *, expires_seconds: int, download_name: str | None = None
    ) -> str: ...


@dataclass(slots=True)
class MinioStorage:
    """MinIO/S3 backend. Creates the bucket on demand (idempotent)."""

    client: Minio
    bucket: str

    def _ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        def _put() -> None:
            self._ensure_bucket()
            self.client.put_object(
                self.bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )

        try:
            await asyncio.to_thread(_put)
        except Exception as exc:  # noqa: BLE001 - map to a uniform StorageError
            raise StorageError(f"put failed: {type(exc).__name__}") from exc

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            response = self.client.get_object(self.bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        try:
            return await asyncio.to_thread(_get)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"get failed: {type(exc).__name__}") from exc

    async def get_stream(
        self, key: str, *, chunk_size: int = STREAM_CHUNK_BYTES
    ) -> AsyncIterator[bytes]:
        """Stream the object from MinIO chunk-wise instead of reading it fully into RAM.
        The (synchronous) connection is read in a thread pool (no event-loop blocking) and
        reliably closed/released in ``finally`` — even on client abort (``GeneratorExit``)
        or read error."""
        # Open the connection eagerly so a transient storage error at connect surfaces as
        # a StorageError BEFORE the response starts (→ 503), not mid-stream.
        try:
            response = await asyncio.to_thread(
                self.client.get_object, self.bucket, key
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"get_stream failed: {type(exc).__name__}") from exc

        async def _iter() -> AsyncIterator[bytes]:
            try:
                while True:
                    chunk = await asyncio.to_thread(response.read, chunk_size)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await asyncio.to_thread(response.close)
                await asyncio.to_thread(response.release_conn)

        return _iter()

    async def remove(self, key: str) -> None:
        try:
            await asyncio.to_thread(self.client.remove_object, self.bucket, key)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"remove failed: {type(exc).__name__}") from exc

    def presigned_get_url(
        self, key: str, *, expires_seconds: int, download_name: str | None = None
    ) -> str:
        # `Content-Disposition: attachment` forces download instead of inline render (no
        # execution). nginx additionally sets `nosniff`.
        extra: dict[str, str] | None = None
        if download_name is not None:
            disposition = f'attachment; filename="{_safe_disposition(download_name)}"'
            extra = {"response-content-disposition": disposition}
        try:
            return self.client.presigned_get_object(
                self.bucket,
                key,
                expires=timedelta(seconds=expires_seconds),
                response_headers=extra,  # type: ignore[arg-type]  # minio: mapping variance
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"presign failed: {type(exc).__name__}") from exc


def _safe_disposition(name: str) -> str:
    """Strip quotes/control characters from the filename (avoid header injection)."""
    return "".join(c for c in name if c.isprintable() and c not in '"\\\r\n')


def build_object_storage(settings: Settings) -> ObjectStorage | None:
    """Build MinIO storage from the settings — ``None`` when storage is off.

    Without ``minio_endpoint`` (DEV/contract CI) uploads stay disabled (503)."""
    if not settings.storage_enabled:
        return None
    from minio import Minio

    assert settings.minio_endpoint is not None
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    return MinioStorage(client=client, bucket=settings.minio_bucket)
