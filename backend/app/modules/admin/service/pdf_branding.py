"""The PDF branding of the branding page (``admin.site``, specs 000891, 000892).

Two slots: the export logo (``logo``) and the footer graphic (``footer``). A slot holds
an upload, a built-in graphic of the render service (the default) or nothing.

The upload is authoritative about the bytes, like the CD logos
(``site_config.cd_logos``): it caps the real size, sniffs the magic bytes (PNG, JPEG,
WebP, SVG or PDF) and lets ClamAV scan them before the object goes to the bucket. SVG
and PDF pass, because the bytes reach the render service only. No route serves them
inline: the file route answers ``application/octet-stream`` with
``Content-Disposition: attachment``.

The service does not commit (spec 000474): the router commits and then calls
``remove_object`` for the key that a change returns, because the old object must stay
until the new row is durable. Every change writes an audit entry (``config_change``,
target type ``pdf_asset``) in its transaction.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.modules.admin.schemas import PdfAssetOut
from app.modules.admin.service.service_base import ConfigServiceBase
from app.modules.audit.actions import AuditAction
from app.modules.files.pdf_branding import BUILTIN, PdfSlot
from app.modules.files.scanner import scan_or_raise
from app.modules.files.storage import StorageError
from app.modules.site_config.cd_logos import (
    ALLOWED_CD_LOGO_MIME,
    MAX_CD_LOGO_BYTES,
    sniff_cd_logo,
)
from app.modules.site_config.models import PdfAsset
from app.settings import Settings, get_settings
from app.shared.errors import (
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
)
from app.shared.filenames import sanitize_display_name, sanitize_storage_name

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.files.storage import ObjectStorage

#: The storage prefix of the PDF branding objects.
PDF_ASSET_PREFIX = "pdf-asset/"


def _out(row: PdfAsset) -> PdfAssetOut:
    return PdfAssetOut(
        builtin=row.builtin is not None, file_name=row.file_name, mime=row.mime, size=row.size
    )


def check_pdf_asset(data: bytes) -> str:
    """Apply the upload policy of the PDF branding and return the sniffed type.

    Raises:
        PayloadTooLargeError: The bytes exceed the cap (413).
        UnsupportedMediaTypeError: The bytes are empty or not an accepted type (415).
    """
    if len(data) > MAX_CD_LOGO_BYTES:
        raise PayloadTooLargeError(f"File exceeds {MAX_CD_LOGO_BYTES} bytes.")
    mime = sniff_cd_logo(data) if data else None
    if mime is None or mime not in ALLOWED_CD_LOGO_MIME:
        raise UnsupportedMediaTypeError(
            "File must be PNG, JPEG, WebP, SVG or PDF (checked from the bytes)."
        )
    return mime


class PdfBrandingService(ConfigServiceBase):
    """Read, upload, reset and delete the graphics of the PDF branding.

    Without explicit settings the upload reads ``get_settings()``, so the virus scan
    never falls back to a skip.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: ObjectStorage | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Bind the service to a session, the object storage and the settings."""
        super().__init__(session, storage=storage)
        self.settings = settings

    async def _row(self, slot: PdfSlot) -> PdfAsset | None:
        return (await self.session.scalars(select(PdfAsset).where(PdfAsset.slot == slot))).first()

    async def get(self, slot: PdfSlot) -> PdfAssetOut | None:
        """Return the graphic of the slot, or ``None`` when the slot is empty."""
        row = await self._row(slot)
        return _out(row) if row is not None else None

    async def _replace(
        self, slot: PdfSlot, row: PdfAsset, actor: str, detail: dict[str, object]
    ) -> str | None:
        old = await self._row(slot)
        old_key = old.object_key if old is not None else None
        if old is not None:
            await self.session.delete(old)
            await self.session.flush()
        self.session.add(row)
        await self.session.flush()
        await self._audit(
            actor,
            AuditAction.CONFIG_CHANGE,
            "pdf_asset",
            row.id,
            {"slot": slot, **detail, "replaced": old is not None},
        )
        return old_key

    async def upload(
        self, slot: PdfSlot, data: bytes, *, filename: str | None, actor: str
    ) -> tuple[PdfAssetOut, str | None]:
        """Check and store the bytes, and make them the graphic of the slot.

        Returns:
            The new graphic, and the object key of the replaced upload or ``None``. The
            caller removes that object after the commit.

        Raises:
            PayloadTooLargeError: The bytes exceed the cap (413).
            UnsupportedMediaTypeError: Not an accepted type, or the virus scan found a
                signature (415).
            ServiceUnavailableError: The storage is off or the write failed, or the
                virus scan is unavailable in production (503).
        """
        mime = check_pdf_asset(data)
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        await scan_or_raise(data, self.settings or get_settings())
        display_name = sanitize_display_name(filename)
        object_key = (
            f"{PDF_ASSET_PREFIX}{slot}/{uuid.uuid4().hex}/{sanitize_storage_name(display_name)}"
        )
        try:
            await self.storage.put(object_key, data, mime)
        except StorageError as exc:
            raise ServiceUnavailableError("Object storage write failed.") from exc
        row = PdfAsset(
            slot=slot,
            object_key=object_key,
            file_name=display_name,
            mime=mime,
            size=len(data),
            created_by=actor,
        )
        old_key = await self._replace(slot, row, actor, {"mime": mime, "size": len(data)})
        return _out(row), old_key

    async def reset(self, slot: PdfSlot, actor: str) -> tuple[PdfAssetOut, str | None]:
        """Set the built-in graphic of the slot again (the STUPA logo, the Skyline).

        Returns:
            The graphic, and the object key of the replaced upload or ``None``.
        """
        row = PdfAsset(slot=slot, builtin=BUILTIN[slot], created_by=actor)
        old_key = await self._replace(slot, row, actor, {"builtin": BUILTIN[slot]})
        return _out(row), old_key

    async def delete(self, slot: PdfSlot, actor: str) -> str | None:
        """Empty the slot; the PDFs then carry no graphic there.

        Returns:
            The object key of the removed upload, or ``None``.

        Raises:
            NotFoundError: The slot is empty (404).
        """
        row = await self._row(slot)
        if row is None:
            raise NotFoundError("The slot is empty.")
        key = row.object_key
        await self.session.delete(row)
        await self._audit(
            actor, AuditAction.CONFIG_CHANGE, "pdf_asset", row.id, {"slot": slot, "deleted": True}
        )
        return key

    async def file_bytes(self, slot: PdfSlot) -> tuple[bytes, str]:
        """Load the upload of the slot from the storage, with its file name.

        The caller decides the media type and must not echo the stored one.

        Raises:
            NotFoundError: The slot holds no upload (404).
            ServiceUnavailableError: The storage is off or unreachable (503).
        """
        row = await self._row(slot)
        if row is None or row.object_key is None:
            raise NotFoundError("The slot holds no upload.")
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        try:
            return await self.storage.get(row.object_key), row.file_name or "file"
        except StorageError as exc:
            raise ServiceUnavailableError("Could not read the file.") from exc

    async def remove_object(self, object_key: str | None) -> None:
        """Drop an object after its row is gone. A storage error must not fail the change."""
        if self.storage is None or object_key is None:
            return
        with contextlib.suppress(StorageError):
            await self.storage.remove(object_key)
