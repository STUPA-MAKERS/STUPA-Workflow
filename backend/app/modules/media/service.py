"""Media service: store, serve and collect the images of the Markdown texts.

``upload`` takes the bytes of one file. It scans the bytes of the client with ClamAV
first (``files.scanner.scan_or_raise``), before Pillow decodes them, because a decoder
bug is reachable only through the decode. Then it cleans them (``images.clean_image``:
sniff, decode, strip the metadata, downscale, encode again), stores the result under
``media/images/<id>`` in the attachment bucket and inserts the ``markdown_image``
row. The stored bytes come from Pillow, never from the client. At most
``CLEAN_CONCURRENCY`` cleans run at the same time in one process.

``open`` streams one image. The router applies the read rule before.

``render_assets`` collects the images of a protocol Markdown for the typst render,
within a budget. It never fails a render: an image that is missing, that the
storage cannot deliver or that passes the budget is left out, and the PDF then shows
its alt text.

``upload_document``, ``open_document``, ``document_info`` and ``render_documents``
do the same for the PDFs that a protocol text embeds (specs 000862, 000868, 000869).
A PDF has no clean re-encode, so the upload scans it, then checks it with pypdf
(``documents.check_pdf``) and stores the bytes of the client. The render loads the
PDFs within their own budget as ``doc-<id>.pdf`` assets.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import KW_ONLY, dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.files.scanner import scan_or_raise
from app.modules.files.storage import ObjectStorage, StorageError
from app.modules.media.documents import (
    PDF_MIME,
    CheckedPdf,
    DocumentRejected,
    DocumentTooLarge,
    check_pdf,
)
from app.modules.media.images import CleanImage, ImageRejected, clean_image
from app.modules.media.models import (
    MarkdownDocument,
    MarkdownImage,
    document_storage_key,
    image_storage_key,
)
from app.modules.media.refs import document_ids_in, document_path, image_ids_in, image_path
from app.modules.media.schemas import MarkdownDocumentOut, MarkdownImageOut
from app.settings import Settings, get_settings
from app.shared.errors import (
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
)
from app.shared.filenames import sanitize_display_name

logger = logging.getLogger("app.media")

#: The most images of one protocol render.
RENDER_MAX_IMAGES: Final[int] = 48
#: The most image bytes of one protocol render.
RENDER_MAX_BYTES: Final[int] = 24 * 1024 * 1024
#: The largest single image of a render: the asset cap of the typst service.
RENDER_MAX_ASSET_BYTES: Final[int] = 8 * 1024 * 1024
#: The most embedded PDFs of one protocol render (spec 000868).
RENDER_MAX_DOCUMENTS: Final[int] = 20
#: The most Anlage pages of one protocol render (spec 000868).
RENDER_MAX_DOCUMENT_PAGES: Final[int] = 300
#: The most PDF bytes of one protocol render.
RENDER_MAX_DOCUMENT_BYTES: Final[int] = 48 * 1024 * 1024
#: The largest single PDF of a render: the asset cap of the typst service.
RENDER_MAX_DOCUMENT_ASSET_BYTES: Final[int] = 20 * 1024 * 1024
#: The most image cleans that run at the same time in one process.
CLEAN_CONCURRENCY: Final[int] = 2

#: Caps the parallel cleans (CPU and memory work in a thread) at ``CLEAN_CONCURRENCY``,
#: so parallel uploads cannot take all the CPU or the memory of the API.
_clean_slots: Final[asyncio.Semaphore] = asyncio.Semaphore(CLEAN_CONCURRENCY)
#: A cancelled request releases ``_clean_slots`` while its thread still works. This
#: semaphore holds the limit in that case too.
_clean_threads: Final[threading.BoundedSemaphore] = threading.BoundedSemaphore(CLEAN_CONCURRENCY)


def _clean_bounded(data: bytes) -> CleanImage:
    """Run ``clean_image`` in one of the ``CLEAN_CONCURRENCY`` thread slots."""
    with _clean_threads:
        return clean_image(data)


def _check_bounded(data: bytes) -> CheckedPdf:
    """Run ``check_pdf`` in one of the ``CLEAN_CONCURRENCY`` thread slots."""
    with _clean_threads:
        return check_pdf(data)


#: Stored type -> the extension of the typst asset name.
_ASSET_EXT: Final[dict[str, str]] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}


def render_asset_name(image_id: uuid.UUID, mime: str) -> str:
    """Return the typst asset name of an image, ``img-<id>.<ext>``."""
    return f"img-{image_id}.{_ASSET_EXT[mime]}"


def document_asset_name(document_id: uuid.UUID) -> str:
    """Return the typst asset name of an embedded PDF, ``doc-<id>.pdf``."""
    return f"doc-{document_id}.pdf"


def _document_out(row: MarkdownDocument) -> MarkdownDocumentOut:
    return MarkdownDocumentOut(
        id=row.id, url=document_path(row.id), name=row.name, size=row.size, pages=row.pages
    )


def _within_budget(
    rows: Sequence[MarkdownDocument], max_count: int, max_bytes: int, max_pages: int
) -> tuple[MarkdownDocument, ...]:
    """Keep the PDFs in order while the count, the bytes and the pages stay in the budget.

    A PDF that does not fit is skipped, and a later, smaller one can still fit. The
    stored size and page count come from the upload, so the choice needs no read.
    """
    if not rows or max_count <= 0:
        return ()
    first, rest = rows[0], rows[1:]
    if first.size > max_bytes or first.pages > max_pages:
        return _within_budget(rest, max_count, max_bytes, max_pages)
    tail = _within_budget(rest, max_count - 1, max_bytes - first.size, max_pages - first.pages)
    return (first, *tail)


@dataclass(frozen=True, slots=True)
class DocumentStream:
    """The bytes of one embedded PDF, their size and the file name."""

    stream: AsyncIterator[bytes]
    name: str
    size: int


@dataclass(frozen=True, slots=True)
class ImageStream:
    """The bytes of one stored image and their headers."""

    stream: AsyncIterator[bytes]
    mime: str
    size: int


@dataclass(frozen=True, slots=True)
class MediaService:
    """Upload, read and render collection of the Markdown images.

    The service is bound to a session, the storage and the upload limits. Without
    ``storage`` an upload gives 503. ``settings`` None means ``get_settings()``.
    """

    session: AsyncSession
    _: KW_ONLY
    storage: ObjectStorage | None
    max_bytes: int = 10 * 1024 * 1024
    max_document_bytes: int = 20 * 1024 * 1024
    settings: Settings | None = None

    async def upload(self, data: bytes) -> MarkdownImageOut:
        """Scan, clean and store one image.

        Without explicit settings the service reads ``get_settings()``, so the scan
        never falls back to a skip.

        Raises:
            ServiceUnavailableError: The storage is off or failed, or the virus scan
                is unavailable in production (503).
            UnsupportedMediaTypeError: The file is no accepted image, or the virus
                scan found a signature (415).
            PayloadTooLargeError: The encoded image is larger than ``max_bytes`` (413).
        """
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        await scan_or_raise(data, self.settings or get_settings())
        try:
            async with _clean_slots:
                image = await asyncio.to_thread(_clean_bounded, data)
        except ImageRejected as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc
        if len(image.data) > self.max_bytes:
            raise PayloadTooLargeError(f"Image exceeds {self.max_bytes} bytes.")
        image_id = uuid.uuid4()
        row = MarkdownImage(
            id=image_id,
            storage_key=image_storage_key(image_id),
            mime=image.mime,
            size=len(image.data),
            width=image.width,
            height=image.height,
        )
        self.session.add(row)
        await self.session.flush()
        try:
            await self.storage.put(row.storage_key, image.data, image.mime)
        except StorageError as exc:
            raise ServiceUnavailableError("Object storage write failed.") from exc
        await self.session.commit()
        logger.info("markdown image stored", extra={"image_id": str(image_id)})
        return MarkdownImageOut(
            id=image_id,
            url=image_path(image_id),
            mime=row.mime,
            width=row.width,
            height=row.height,
            size=row.size,
        )

    async def open(self, image_id: uuid.UUID) -> ImageStream:
        """Return the stream of one image.

        Raises:
            NotFoundError: The id is unknown (404).
            ServiceUnavailableError: The storage is off or failed (503).
        """
        row = await self.session.get(MarkdownImage, image_id)
        if row is None:
            raise NotFoundError("image not found")
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        try:
            stream = await self.storage.get_stream(row.storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Image temporarily unavailable.") from exc
        return ImageStream(stream=stream, mime=row.mime, size=row.size)

    async def render_assets(
        self,
        markdown: str,
        *,
        max_images: int = RENDER_MAX_IMAGES,
        max_bytes: int = RENDER_MAX_BYTES,
        max_asset_bytes: int = RENDER_MAX_ASSET_BYTES,
    ) -> dict[str, bytes]:
        """Load the images of a Markdown text as typst assets.

        The ids come in the order of their first appearance. An image that is
        unknown, that the storage cannot deliver, that is larger than
        ``max_asset_bytes``, or that does not fit into the remaining budget
        (``max_images``, ``max_bytes``) is left out. The method never raises for
        an image.

        Returns:
            ``{"img-<id>.<ext>": bytes}``, empty without storage or without images.
        """
        ids = image_ids_in(markdown)
        if self.storage is None or not ids:
            return {}
        rows = (
            await self.session.scalars(select(MarkdownImage).where(MarkdownImage.id.in_(ids)))
        ).all()
        by_id = {row.id: row for row in rows}
        return await self._load(
            self.storage,
            [by_id[i] for i in ids if i in by_id],
            max_images=max_images,
            max_bytes=max_bytes,
            max_asset_bytes=max_asset_bytes,
        )

    @staticmethod
    async def _load(
        storage: ObjectStorage,
        rows: Sequence[MarkdownImage],
        *,
        max_images: int,
        max_bytes: int,
        max_asset_bytes: int,
    ) -> dict[str, bytes]:
        assets: dict[str, bytes] = {}
        total = 0
        for row in rows:
            if len(assets) >= max_images:
                break
            if row.size > max_asset_bytes or total + row.size > max_bytes:
                continue
            try:
                data = await storage.get(row.storage_key)
            except StorageError:
                logger.warning(
                    "markdown image missing for the render", extra={"image_id": str(row.id)}
                )
                continue
            if len(data) > max_asset_bytes or total + len(data) > max_bytes:
                continue
            assets[render_asset_name(row.id, row.mime)] = data
            total += len(data)
        return assets

    # -- embedded PDFs (specs 000862, 000868, 000869) ------------------------

    async def upload_document(self, data: bytes, filename: str | None) -> MarkdownDocumentOut:
        """Scan, check and store one PDF for a protocol text.

        The ClamAV scan runs before pypdf reads the bytes. The stored bytes are the
        bytes of the client: a PDF has no clean re-encode.

        Raises:
            ServiceUnavailableError: The storage is off or failed, or the virus scan
                is unavailable in production (503).
            UnsupportedMediaTypeError: No PDF, unreadable, encrypted, or the virus
                scan found a signature (415).
            PayloadTooLargeError: Over ``max_document_bytes`` or over 100 pages (413).
        """
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        if len(data) > self.max_document_bytes:
            raise PayloadTooLargeError(f"PDF exceeds {self.max_document_bytes} bytes.")
        await scan_or_raise(data, self.settings or get_settings())
        checked = await self._checked(data)
        document_id = uuid.uuid4()
        row = MarkdownDocument(
            id=document_id,
            storage_key=document_storage_key(document_id),
            name=sanitize_display_name(filename, default="Dokument.pdf"),
            size=len(data),
            pages=checked.pages,
        )
        self.session.add(row)
        await self.session.flush()
        try:
            await self.storage.put(row.storage_key, data, PDF_MIME)
        except StorageError as exc:
            raise ServiceUnavailableError("Object storage write failed.") from exc
        logger.info("markdown document stored", extra={"document_id": str(document_id)})
        return _document_out(row)

    @staticmethod
    async def _checked(data: bytes) -> CheckedPdf:
        """Run ``check_pdf`` in a clean slot and map its refusals to problem errors."""
        try:
            async with _clean_slots:
                return await asyncio.to_thread(_check_bounded, data)
        except DocumentRejected as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc
        except DocumentTooLarge as exc:
            raise PayloadTooLargeError(str(exc)) from exc

    async def document_info(self, document_id: uuid.UUID) -> MarkdownDocumentOut:
        """Return the name, size and page count of one PDF.

        Raises:
            NotFoundError: The id is unknown (404).
        """
        row = await self.session.get(MarkdownDocument, document_id)
        if row is None:
            raise NotFoundError("document not found")
        return _document_out(row)

    async def open_document(self, document_id: uuid.UUID) -> DocumentStream:
        """Return the stream of one PDF.

        Raises:
            NotFoundError: The id is unknown (404).
            ServiceUnavailableError: The storage is off or failed (503).
        """
        row = await self.session.get(MarkdownDocument, document_id)
        if row is None:
            raise NotFoundError("document not found")
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        try:
            stream = await self.storage.get_stream(row.storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Document temporarily unavailable.") from exc
        return DocumentStream(stream=stream, name=row.name, size=row.size)

    async def render_documents(
        self,
        markdown: str,
        *,
        max_count: int = RENDER_MAX_DOCUMENTS,
        max_bytes: int = RENDER_MAX_DOCUMENT_BYTES,
        max_asset_bytes: int = RENDER_MAX_DOCUMENT_ASSET_BYTES,
        max_pages: int = RENDER_MAX_DOCUMENT_PAGES,
    ) -> dict[str, bytes]:
        """Load the embedded PDFs of a Markdown text as typst assets.

        The ids come in the order of their first appearance. A PDF that is unknown,
        larger than ``max_asset_bytes``, past the budget (``max_count``, ``max_bytes``,
        ``max_pages``) or that the storage cannot deliver is left out; typst then
        prints "Anlage nicht eingebunden" at its place. The method never raises for a
        PDF, so a PDF never makes the render fail (spec 000868).

        Returns:
            ``{"doc-<id>.pdf": bytes}``, empty without storage or without PDFs.
        """
        ids = document_ids_in(markdown)
        if self.storage is None or not ids:
            return {}
        rows = (
            await self.session.scalars(select(MarkdownDocument).where(MarkdownDocument.id.in_(ids)))
        ).all()
        by_id = {row.id: row for row in rows}
        ordered = [by_id[i] for i in ids if i in by_id and by_id[i].size <= max_asset_bytes]
        kept = _within_budget(ordered, max_count, max_bytes, max_pages)
        loaded = [(row, await self._fetch(self.storage, row)) for row in kept]
        return {
            document_asset_name(row.id): data
            for row, data in loaded
            if data is not None and len(data) == row.size
        }

    @staticmethod
    async def _fetch(storage: ObjectStorage, row: MarkdownDocument) -> bytes | None:
        """Read one stored PDF, or None when the storage cannot deliver it."""
        try:
            return await storage.get(row.storage_key)
        except StorageError:
            logger.warning(
                "markdown document missing for the render", extra={"document_id": str(row.id)}
            )
            return None
