"""An in-memory object storage and the route wiring for download tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.deps import DbSession, SettingsDep
from app.modules.files.router import get_files_service
from app.modules.files.service import FilesService


class MemoryStorage:
    """Keep the objects in a dict; ``remove`` of a missing key does nothing."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def get_stream(self, key: str, *, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        async def _iter() -> AsyncIterator[bytes]:
            yield self.blobs[key]

        return _iter()

    async def remove(self, key: str) -> None:
        self.blobs.pop(key, None)


def wire_storage(app: FastAPI, storage: MemoryStorage) -> None:
    """Serve the attachment routes from ``storage``."""

    def _files(session: DbSession, request_settings: SettingsDep) -> FilesService:
        return FilesService(session, storage=storage, settings=request_settings)  # pyright: ignore[reportArgumentType]

    app.dependency_overrides[get_files_service] = _files
