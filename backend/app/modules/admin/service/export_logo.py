"""The export logo of the branding page (``admin.site``, spec 000891).

One logo for every exported PDF except the protocol. The upload is authoritative about
the bytes, like the CD logos (``site_config.cd_logos``): it caps the real size, sniffs
the magic bytes (PNG, JPEG, WebP, SVG or PDF) and lets ClamAV scan them before the
object goes to the bucket. SVG and PDF pass, because the bytes reach the render service
only. No route serves them inline: the file route answers
``application/octet-stream`` with ``Content-Disposition: attachment``.

A new upload replaces the row. The service does not commit (spec 000474): the router
commits and then calls ``remove_object`` for the key that the change returns, because
the old object must stay until the new row is durable. Every change writes an audit
entry (``config_change``, target type ``export_logo``) in its transaction.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.modules.admin.schemas import ExportLogoOut
from app.modules.admin.service.service_base import ConfigServiceBase
from app.modules.audit.actions import AuditAction
from app.modules.files.scanner import scan_or_raise
from app.modules.files.storage import StorageError
from app.modules.site_config.cd_logos import (
    ALLOWED_CD_LOGO_MIME,
    MAX_CD_LOGO_BYTES,
    sniff_cd_logo,
)
from app.modules.site_config.models import ExportLogo
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

#: The storage prefix of the export logo objects.
EXPORT_LOGO_PREFIX = "export-logo/"


def _out(row: ExportLogo) -> ExportLogoOut:
    return ExportLogoOut(file_name=row.file_name, mime=row.mime, size=row.size)


def check_export_logo(data: bytes) -> str:
    """Apply the upload policy of the export logo and return the sniffed type.

    Raises:
        PayloadTooLargeError: The bytes exceed the cap (413).
        UnsupportedMediaTypeError: The bytes are empty or not an accepted type (415).
    """
    if len(data) > MAX_CD_LOGO_BYTES:
        raise PayloadTooLargeError(f"Logo exceeds {MAX_CD_LOGO_BYTES} bytes.")
    mime = sniff_cd_logo(data) if data else None
    if mime is None or mime not in ALLOWED_CD_LOGO_MIME:
        raise UnsupportedMediaTypeError(
            "Logo must be PNG, JPEG, WebP, SVG or PDF (checked from the bytes)."
        )
    return mime


class ExportLogoService(ConfigServiceBase):
    """Read, upload and delete the export logo.

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

    async def _row(self) -> ExportLogo | None:
        return (await self.session.scalars(select(ExportLogo))).first()

    async def get(self) -> ExportLogoOut | None:
        """Return the export logo, or ``None`` when none is set."""
        row = await self._row()
        return _out(row) if row is not None else None

    async def upload(
        self, data: bytes, *, filename: str | None, actor: str
    ) -> tuple[ExportLogoOut, str | None]:
        """Check and store the bytes, and replace the export logo.

        Returns:
            The new logo, and the object key of the replaced logo or ``None``. The caller
            removes that object after the commit.

        Raises:
            PayloadTooLargeError: The bytes exceed the cap (413).
            UnsupportedMediaTypeError: Not an accepted type, or the virus scan found a
                signature (415).
            ServiceUnavailableError: The storage is off or the write failed, or the
                virus scan is unavailable in production (503).
        """
        mime = check_export_logo(data)
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        await scan_or_raise(data, self.settings or get_settings())
        display_name = sanitize_display_name(filename)
        object_key = f"{EXPORT_LOGO_PREFIX}{uuid.uuid4().hex}/{sanitize_storage_name(display_name)}"
        try:
            await self.storage.put(object_key, data, mime)
        except StorageError as exc:
            raise ServiceUnavailableError("Object storage write failed.") from exc
        old = await self._row()
        old_key = old.object_key if old is not None else None
        if old is not None:
            await self.session.delete(old)
            await self.session.flush()
        row = ExportLogo(
            object_key=object_key,
            file_name=display_name,
            mime=mime,
            size=len(data),
            created_by=actor,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(
            actor,
            AuditAction.CONFIG_CHANGE,
            "export_logo",
            row.id,
            {"mime": mime, "size": len(data), "replaced": old_key is not None},
        )
        return _out(row), old_key

    async def delete(self, actor: str) -> str:
        """Remove the export logo; the exports then carry no logo.

        Returns:
            The object key, which the caller removes after the commit.

        Raises:
            NotFoundError: No export logo is set (404).
        """
        row = await self._row()
        if row is None:
            raise NotFoundError("No export logo is set.")
        key = row.object_key
        await self.session.delete(row)
        await self._audit(
            actor, AuditAction.CONFIG_CHANGE, "export_logo", row.id, {"deleted": True}
        )
        return key

    async def file_bytes(self) -> tuple[bytes, str]:
        """Load the export logo from the storage, with its file name.

        The caller decides the media type and must not echo the stored one.

        Raises:
            NotFoundError: No export logo is set (404).
            ServiceUnavailableError: The storage is off or unreachable (503).
        """
        row = await self._row()
        if row is None:
            raise NotFoundError("No export logo is set.")
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        try:
            return await self.storage.get(row.object_key), row.file_name
        except StorageError as exc:
            raise ServiceUnavailableError("Could not read the export logo.") from exc

    async def remove_object(self, object_key: str | None) -> None:
        """Drop an object after its row is gone. A storage error must not fail the change."""
        if self.storage is None or object_key is None:
            return
        with contextlib.suppress(StorageError):
            await self.storage.remove(object_key)
