"""Object-Storage-Abstraktion (MinIO/S3) + signierte URLs (security.md §6).

Der Service kennt nur das :class:`ObjectStorage`-Protokoll — nie den konkreten Client.
``MinioStorage`` kapselt den (synchronen) ``minio``-Client und reicht blockierende Calls
über ``asyncio.to_thread`` an einen Threadpool (kein Blockieren der Event-Loop). Es gibt
keinen direkten Bucket-Zugriff von außen.

``presigned_get_url`` liefert eine kurzlebige S3v4-signierte GET-URL und wird intern
genutzt (PDF-Modul). Anhang-**Downloads** der files-API laufen dagegen NICHT über eine
signierte URL, sondern server-seitig über die authz-gated ``/api/attachments/{id}/download``-
Route — MinIO liegt im internen Docker-Netz ohne Port-Publish, eine signierte URL wäre vom
Browser unerreichbar (#AUD-055; s. ``service.signed_url``).

``minio`` wird **lazy** importiert: ohne Upload-Pfad (Contract-CI) lädt die Lib nie.
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

# Default-Chunk-Größe für den gestreamten Download (#AUD-073): Objekt wird in Häppchen
# aus MinIO gelesen, nicht komplett in den Speicher gepuffert.
STREAM_CHUNK_BYTES = 64 * 1024


class StorageError(RuntimeError):
    """Object-Storage nicht erreichbar / Operation fehlgeschlagen."""


class ObjectStorage(Protocol):
    """Vom Service genutzte Storage-Schnittstelle (put/get/remove/signierte URL)."""

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
    """MinIO/S3-Backend. Stellt den Bucket bei Bedarf her (idempotent)."""

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
        except Exception as exc:  # noqa: BLE001 — auf einheitlichen StorageError mappen
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
        """Objekt chunk-weise aus MinIO streamen statt komplett in den RAM zu lesen
        (#AUD-073). Die (synchrone) Verbindung wird in einem Threadpool gelesen (kein
        Blockieren der Event-Loop) und im ``finally`` zuverlässig geschlossen/freigegeben
        — auch bei Client-Abbruch (``GeneratorExit``) oder Lese-Fehler."""
        # Verbindung EAGER öffnen, damit ein transienter Storage-Fehler beim Connect als
        # StorageError VOR dem Response-Start (→ 503) sichtbar wird, nicht mitten im Stream.
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
        # `Content-Disposition: attachment` erzwingt Download statt Inline-Render
        # (security.md §6: keine Ausführung). nginx setzt zusätzlich `nosniff`.
        extra: dict[str, str] | None = None
        if download_name is not None:
            disposition = f'attachment; filename="{_safe_disposition(download_name)}"'
            extra = {"response-content-disposition": disposition}
        try:
            return self.client.presigned_get_object(
                self.bucket,
                key,
                expires=timedelta(seconds=expires_seconds),
                response_headers=extra,  # type: ignore[arg-type]  # minio: Mapping-Varianz
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"presign failed: {type(exc).__name__}") from exc


def _safe_disposition(name: str) -> str:
    """Quotes/Steuerzeichen aus dem Dateinamen entfernen (Header-Injection vermeiden)."""
    return "".join(c for c in name if c.isprintable() and c not in '"\\\r\n')


def build_object_storage(settings: Settings) -> ObjectStorage | None:
    """MinIO-Storage aus den Settings bauen — ``None``, wenn Storage »aus« ist.

    Ohne ``minio_endpoint`` (DEV/Contract-CI) bleibt der Upload deaktiviert (503)."""
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
