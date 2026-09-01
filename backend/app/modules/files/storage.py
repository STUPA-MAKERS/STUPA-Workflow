"""Object storage abstraction over MinIO/S3, plus signed URLs.

The service knows only the ``ObjectStorage`` protocol, never the concrete client.
``MinioStorage`` wraps the synchronous ``minio`` client. It hands every blocking call to
a thread pool with ``asyncio.to_thread``, so the event loop never blocks. Nothing outside
reaches the bucket directly.

``presigned_get_url`` returns a short-lived S3v4-signed GET URL. Only internal callers
use it, such as the PDF module. An attachment download of the files API does NOT use a
signed URL. It streams from the server over the ``/api/attachments/{id}/download`` route
that the authorization layer gates. MinIO runs on the internal Docker network and
publishes no port, so the browser could not reach a signed URL.

The module imports ``minio`` lazily. Without the upload path (contract CI) the library
never loads.
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

# Default chunk size of the streamed download. The reader never holds the whole object
# in memory.
STREAM_CHUNK_BYTES = 64 * 1024


class StorageError(RuntimeError):
    """The object storage is unreachable or the operation failed."""


class ObjectStorage(Protocol):
    """Storage interface that the service uses: put, get, remove and signed URL."""

    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def get_stream(
        self, key: str, *, chunk_size: int = STREAM_CHUNK_BYTES
    ) -> AsyncIterator[bytes]: ...

    async def remove(self, key: str) -> None: ...

    async def list_keys(self) -> list[str]: ...

    async def put_file(self, key: str, path: str, content_type: str) -> None: ...

    async def get_file(self, key: str, path: str) -> None: ...

    def presigned_get_url(
        self, key: str, *, expires_seconds: int, download_name: str | None = None
    ) -> str: ...


@dataclass(slots=True)
class MinioStorage:
    """MinIO/S3 backend.

    The backend creates the bucket on demand. The creation is idempotent.
    """

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
        """Stream the object from MinIO chunk by chunk instead of reading it into RAM.

        A thread pool reads the synchronous connection, so the event loop never blocks.
        The ``finally`` block always closes and releases the connection, also on a client
        abort (``GeneratorExit``) and on a read error.
        """
        # Open the connection eagerly. A transient storage error at connect then surfaces
        # as a StorageError BEFORE the response starts, that is 503, not mid-stream.
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

    async def list_keys(self) -> list[str]:
        """Return every object key in the bucket.

        A backup walks the whole attachment bucket, and a restore compares against it
        to find the objects the archive does not hold. A missing bucket lists empty
        rather than raising, because a stack that never uploaded anything is not an
        error state.
        """

        def _list() -> list[str]:
            if not self.client.bucket_exists(self.bucket):
                return []
            return [
                obj.object_name
                for obj in self.client.list_objects(self.bucket, recursive=True)
                if obj.object_name is not None
            ]

        try:
            return await asyncio.to_thread(_list)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"list failed: {type(exc).__name__}") from exc

    async def put_file(self, key: str, path: str, content_type: str) -> None:
        """Upload straight from a file on disk, so a large archive never buffers."""

        def _put() -> None:
            self._ensure_bucket()
            self.client.fput_object(self.bucket, key, path, content_type=content_type)

        try:
            await asyncio.to_thread(_put)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"put_file failed: {type(exc).__name__}") from exc

    async def get_file(self, key: str, path: str) -> None:
        """Download straight to a file on disk, the read counterpart of `put_file`."""
        try:
            await asyncio.to_thread(self.client.fget_object, self.bucket, key, path)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"get_file failed: {type(exc).__name__}") from exc

    def presigned_get_url(
        self, key: str, *, expires_seconds: int, download_name: str | None = None
    ) -> str:
        # `Content-Disposition: attachment` forces a download instead of an inline
        # render, so nothing executes. nginx also sets `nosniff`.
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
    """Strip quotes and control characters from the filename to block header injection."""
    return "".join(c for c in name if c.isprintable() and c not in '"\\\r\n')


def build_object_storage(
    settings: Settings, *, bucket: str | None = None
) -> ObjectStorage | None:
    """Build the MinIO storage from the settings.

    Without ``minio_endpoint`` (development or contract CI) uploads stay off and give
    503.

    Args:
        settings: Runtime settings holding the MinIO endpoint and credentials.
        bucket: Bucket override. The backup module passes its own bucket, so the
            archives never share a namespace with the attachments.

    Returns:
        The storage, or ``None`` when storage is off.
    """
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
    return MinioStorage(client=client, bucket=bucket or settings.minio_bucket)
