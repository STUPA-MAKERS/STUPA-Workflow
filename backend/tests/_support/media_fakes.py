"""In-memory fakes of the media unit tests: a session and an object storage.

`MediaSession` keeps the added `MarkdownImage` and `MarkdownDocument` rows and
answers `get` and `scalars` from the rows of the asked model. `MediaStorage` raises
`StorageError` for a missing key, like MinIO. `add_image` and `add_document` store one
object and its row.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.files.storage import StorageError
from app.modules.media.models import (
    MarkdownDocument,
    MarkdownImage,
    document_storage_key,
    image_storage_key,
)
from tests._support.files_fakes import FakeStorage


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class MediaSession:
    """In-memory session: `get` and `scalars` read the added rows."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.flushed = 0
        self.committed = 0

    def add(self, row: Any) -> None:
        self.rows[row.id] = row

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def get(self, model: type, ident: uuid.UUID) -> Any:
        row = self.rows.get(ident)
        return row if isinstance(row, model) else None

    async def scalars(self, stmt: Any) -> _Result:
        model = stmt.column_descriptions[0]["entity"]
        return _Result([row for row in self.rows.values() if isinstance(row, model)])


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


def add_document(
    session: MediaSession,
    storage: MediaStorage,
    data: bytes,
    *,
    name: str = "Dokument.pdf",
    pages: int = 1,
) -> uuid.UUID:
    document_id = uuid.uuid4()
    key = document_storage_key(document_id)
    storage.objects[key] = (data, "application/pdf")
    session.add(
        MarkdownDocument(
            id=document_id, storage_key=key, name=name, size=len(data), pages=pages
        )
    )
    return document_id
