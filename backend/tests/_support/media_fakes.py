"""In-memory fakes of the media unit tests: a session and an object storage.

`MediaSession` keeps the added `MarkdownImage` rows and answers `get` and `scalars`
from them. `MediaStorage` raises `StorageError` for a missing key, like MinIO.
`add_image` stores one image object and its row.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.files.storage import StorageError
from app.modules.media.models import MarkdownImage, image_storage_key
from tests._support.files_fakes import FakeStorage


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class MediaSession:
    """In-memory session: `get` and `scalars` read the added rows."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, MarkdownImage] = {}
        self.flushed = 0
        self.committed = 0

    def add(self, row: MarkdownImage) -> None:
        self.rows[row.id] = row

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def get(self, _model: type, ident: uuid.UUID) -> MarkdownImage | None:
        return self.rows.get(ident)

    async def scalars(self, _stmt: object) -> _Result:
        return _Result(list(self.rows.values()))


class MediaStorage(FakeStorage):
    """`get` of a missing key raises `StorageError`, like MinIO."""

    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise StorageError("get failed: NoSuchKey")
        return await super().get(key)


def add_image(
    session: MediaSession, storage: MediaStorage, data: bytes, mime: str = "image/png"
) -> uuid.UUID:
    image_id = uuid.uuid4()
    key = image_storage_key(image_id)
    storage.objects[key] = (data, mime)
    session.add(
        MarkdownImage(id=image_id, storage_key=key, mime=mime, size=len(data), width=1, height=1)
    )
    return image_id
