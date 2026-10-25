"""CRUD for the corporate-design variants and their logos (`admin.cd_variants`).

Every mutation writes an audit entry (`AuditAction.CONFIG_CHANGE`, target type
``cd_variant``) in the same transaction as the change, like the other admin
services.

The upload path is authoritative about the bytes. It caps the real size, sniffs
the magic bytes and compares them against the declared type. ClamAV then scans
the bytes before the object goes to the bucket (`files.scanner.scan_or_raise`),
because the stored bytes are the bytes of the client: the upload does not encode
them again. The allowlist adds
SVG and PDF, because these bytes only ever reach the typst renderer. The
download path therefore forces an attachment disposition and never answers with
``image/svg+xml`` — see `app.modules.admin.router.get_cd_variant_logo_file`.

The square slot is the exception. Its upload accepts PNG, JPEG and WebP only and
checks the pixel size (`cd_logos.check_square_logo`). A variant holds at most one
square logo, so a new upload replaces the old row and its object. Two routes serve
it inline: the admin thumbnail and `GET /gremien/{id}/logo`. Both go through
`SquareLogoRef`, which only a square row with a raster type can produce.
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.modules.admin.cd_logos import (
    ALLOWED_CD_LOGO_MIME,
    ALLOWED_SQUARE_LOGO_MIME,
    MAX_CD_LOGO_BYTES,
    LogoSlot,
    check_square_logo,
    sniff_cd_logo,
)
from app.modules.admin.models import CdVariant, CdVariantLogo, Gremium
from app.modules.admin.schemas import (
    CdVariantCreate,
    CdVariantLogoOut,
    CdVariantLogoReorder,
    CdVariantLogoVendoredCreate,
    CdVariantOptionOut,
    CdVariantOut,
    CdVariantUpdate,
)
from app.modules.admin.service.service_base import ConfigServiceBase
from app.modules.audit.actions import AuditAction
from app.modules.files.scanner import scan_or_raise
from app.modules.files.storage import ObjectStorage, StorageError
from app.settings import Settings, get_settings
from app.shared.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
    ValidationProblem,
)
from app.shared.filenames import sanitize_display_name, sanitize_storage_name

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

#: Prefix of every CD-logo object in the bucket. It keeps the logos apart from the
#: attachments and the invoices.
CD_LOGO_PREFIX = "cd-logos/"


def _slot(value: str) -> LogoSlot:
    """Narrow the stored text to the closed set. The DB check holds the invariant."""
    if value == "footer":
        return "footer"
    if value == "square":
        return "square"
    return "title"


@dataclass(frozen=True, slots=True)
class SquareLogoRef:
    """A square logo that may render inline in the browser.

    Only `CdVariantService._square_ref` builds one, and only from a square row with
    an uploaded raster object.

    Attributes:
        logo_id: Id of the ``cd_variant_logo`` row. A new upload is a new row, so
            the id is a strong validator for the bytes.
        object_key: Key of the object in the bucket.
        mime: The sniffed raster type, one of ``ALLOWED_SQUARE_LOGO_MIME``.
    """

    logo_id: uuid.UUID
    object_key: str
    mime: str

    @property
    def etag(self) -> str:
        """Return the strong entity tag of the logo bytes."""
        return f'"{self.logo_id.hex}"'


def _logo_out(row: CdVariantLogo) -> CdVariantLogoOut:
    return CdVariantLogoOut(
        id=row.id,
        slot=_slot(row.slot),
        position=row.position,
        vendored_name=row.vendored_name,
        file_name=row.file_name,
        mime=row.mime,
        size=row.size,
    )


def _check_render_logo(data: bytes) -> str:
    """Apply the upload policy of a title or footer logo and return the sniffed type.

    Raises:
        PayloadTooLargeError: The bytes exceed the cap (413).
        UnsupportedMediaTypeError: The bytes are empty or not an accepted type (415).
    """
    if len(data) > MAX_CD_LOGO_BYTES:
        raise PayloadTooLargeError(f"Logo exceeds {MAX_CD_LOGO_BYTES} bytes.")
    if not data:
        raise UnsupportedMediaTypeError("Empty file.")
    mime = sniff_cd_logo(data)
    if mime is None or mime not in ALLOWED_CD_LOGO_MIME:
        raise UnsupportedMediaTypeError(
            "Logo must be PNG, JPEG, WebP, SVG or PDF (checked from the bytes)."
        )
    return mime


def _square_ref(row: CdVariantLogo | None) -> SquareLogoRef | None:
    """Build the inline reference, or ``None`` for a row that must not render inline."""
    if (
        row is None
        or row.slot != "square"
        or row.object_key is None
        or row.mime is None
        or row.mime not in ALLOWED_SQUARE_LOGO_MIME
    ):
        return None
    return SquareLogoRef(logo_id=row.id, object_key=row.object_key, mime=row.mime)


def _variant_out(row: CdVariant, logos: list[CdVariantLogo]) -> CdVariantOut:
    return CdVariantOut(
        id=row.id,
        key=row.key,
        name=row.name,
        base_variant="protocol" if row.base_variant == "protocol" else "report",
        logos=[_logo_out(logo) for logo in logos],
    )


class CdVariantService(ConfigServiceBase):
    """Corporate-design variants: CRUD, logo upload, vendored logos, ordering.

    Without explicit settings the logo upload reads ``get_settings()``, so the virus
    scan never falls back to a skip.
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

    async def list_variants(self) -> list[CdVariantOut]:
        """List the CD variants with their logos."""
        rows = (await self.session.scalars(select(CdVariant).order_by(CdVariant.name))).all()
        by_variant: dict[uuid.UUID, list[CdVariantLogo]] = {row.id: [] for row in rows}
        logos = (
            await self.session.scalars(
                select(CdVariantLogo).order_by(
                    CdVariantLogo.slot, CdVariantLogo.position, CdVariantLogo.id
                )
            )
        ).all()
        for logo in logos:
            bucket = by_variant.get(logo.variant_id)
            if bucket is not None:
                bucket.append(logo)
        return [_variant_out(row, by_variant[row.id]) for row in rows]

    async def list_variant_options(self) -> list[CdVariantOptionOut]:
        """Slim list for the Gremium dropdown: id, key and display name."""
        rows = (await self.session.scalars(select(CdVariant).order_by(CdVariant.name))).all()
        return [CdVariantOptionOut(id=r.id, key=r.key, name=r.name) for r in rows]

    async def create_variant(self, payload: CdVariantCreate, actor: str) -> CdVariantOut:
        """Create a variant.

        Raises:
            ConflictError: The key already exists (409).
        """
        if await self._by_key(payload.key) is not None:
            raise ConflictError(f"cd variant key {payload.key!r} already exists")
        row = CdVariant(key=payload.key, name=payload.name, base_variant=payload.base_variant)
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "cd_variant", row.id)
        await self.session.commit()
        return _variant_out(row, [])

    async def update_variant(
        self, variant_id: UUID, payload: CdVariantUpdate, actor: str
    ) -> CdVariantOut:
        """Patch the display name or the base variant.

        Raises:
            NotFoundError: No variant has this id (404).
            ConflictError: The payload tries to change the immutable key (409).
        """
        row = await self._get_or_404(variant_id)
        if payload.key is not None and payload.key != row.key:
            raise ConflictError("cd variant key is immutable")
        if payload.name is not None:
            row.name = payload.name
        if payload.base_variant is not None:
            row.base_variant = payload.base_variant
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "cd_variant", row.id)
        await self.session.commit()
        return _variant_out(row, await self._logos_of(row.id))

    async def delete_variant(self, variant_id: UUID, actor: str) -> None:
        """Delete a variant and its logos.

        Raises:
            NotFoundError: No variant has this id (404).
            ConflictError: A Gremium still references the variant (409). The FK
                is RESTRICT, so this pre-check keeps the Gremium intact and
                writes no audit entry for a doomed delete.
        """
        row = await self._get_or_404(variant_id)
        in_use = await self.session.scalar(
            select(Gremium.id).where(Gremium.cd_variant_id == variant_id).limit(1)
        )
        if in_use is not None:
            raise ConflictError("cd variant is still referenced by a gremium")
        keys = [
            logo.object_key
            for logo in await self._logos_of(variant_id)
            if logo.object_key is not None
        ]
        await self.session.delete(row)
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "cd_variant", variant_id)
        await self.session.commit()
        for key in keys:
            await self._remove_object(key)

    async def add_vendored_logo(
        self, variant_id: UUID, payload: CdVariantLogoVendoredCreate, actor: str
    ) -> CdVariantLogoOut:
        """Add a logo that the render service ships.

        Raises:
            NotFoundError: No variant has this id (404).
        """
        await self._get_or_404(variant_id)
        row = CdVariantLogo(
            variant_id=variant_id,
            slot=payload.slot,
            position=await self._next_position(variant_id, payload.slot),
            vendored_name=payload.vendored_name,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "cd_variant", variant_id)
        await self.session.commit()
        return _logo_out(row)

    async def upload_logo(
        self,
        variant_id: UUID,
        data: bytes,
        *,
        slot: LogoSlot,
        filename: str | None,
        actor: str,
    ) -> CdVariantLogoOut:
        """Validate the uploaded bytes and store them under the ``cd-logos/`` prefix.

        A square logo replaces the square logo that the variant holds already. The
        old row goes in the same transaction, and its object goes after the commit.

        Raises:
            NotFoundError: No variant has this id (404).
            PayloadTooLargeError: The bytes exceed the cap (413).
            UnsupportedMediaTypeError: The magic bytes are not one of the
                accepted types, or the virus scan found a signature (415).
            ValidationProblem: A square logo is not square, too small or has an
                unreadable header (422).
            ServiceUnavailableError: The object storage is off or the write
                failed, or the virus scan is unavailable in production (503).
        """
        await self._get_or_404(variant_id)
        mime = check_square_logo(data) if slot == "square" else _check_render_logo(data)
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        await scan_or_raise(data, self.settings or get_settings())
        display_name = sanitize_display_name(filename)
        object_key = f"{CD_LOGO_PREFIX}{uuid.uuid4().hex}/{sanitize_storage_name(display_name)}"
        try:
            await self.storage.put(object_key, data, mime)
        except StorageError as exc:
            raise ServiceUnavailableError("Object storage write failed.") from exc
        replaced: list[CdVariantLogo] = []
        if slot == "square":
            replaced = await self._drop_square_logos(variant_id)
            position = 0
        else:
            position = await self._next_position(variant_id, slot)
        row = CdVariantLogo(
            variant_id=variant_id,
            slot=slot,
            position=position,
            object_key=object_key,
            file_name=display_name,
            mime=mime,
            size=len(data),
        )
        self.session.add(row)
        await self.session.flush()
        audit_data = (
            {"slot": "square", "replacedLogoIds": [str(old.id) for old in replaced]}
            if replaced
            else None
        )
        await self._audit(
            actor, AuditAction.CONFIG_CHANGE, "cd_variant", variant_id, audit_data
        )
        await self.session.commit()
        for old in replaced:
            if old.object_key is not None:
                await self._remove_object(old.object_key)
        return _logo_out(row)

    async def _drop_square_logos(self, variant_id: UUID) -> list[CdVariantLogo]:
        """Delete the square rows of a variant and flush, before the new row goes in.

        The variant row is locked first, so two concurrent uploads queue instead of
        hitting the unique index. The flush matters: the unit of work runs inserts
        before deletes, so without it the partial unique index refuses the new row.
        """
        await self.session.execute(
            select(CdVariant.id).where(CdVariant.id == variant_id).with_for_update()
        )
        rows = [logo for logo in await self._logos_of(variant_id) if logo.slot == "square"]
        for old in rows:
            await self.session.delete(old)
        if rows:
            await self.session.flush()
        return rows

    async def logo_file_bytes(self, logo_id: UUID) -> tuple[bytes, str]:
        """Load an uploaded logo from the object storage.

        Returns:
            The bytes and the stored file name. The caller decides the media
            type — it must not echo the stored one.

        Raises:
            NotFoundError: No logo has this id, or the logo is vendored (404).
            ServiceUnavailableError: The object storage is off or unreachable (503).
        """
        row = await self.session.get(CdVariantLogo, logo_id)
        if row is None or row.object_key is None:
            raise NotFoundError(f"cd variant logo {logo_id} not found")
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        try:
            data = await self.storage.get(row.object_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Could not read CD logo.") from exc
        return data, row.file_name or "logo"

    async def admin_square_logo(self, logo_id: UUID) -> SquareLogoRef:
        """Return the square logo with this id for the inline admin thumbnail.

        Raises:
            NotFoundError: No logo has this id, or it is not a square upload (404).
        """
        ref = _square_ref(await self.session.get(CdVariantLogo, logo_id))
        if ref is None:
            raise NotFoundError(f"square logo {logo_id} not found")
        return ref

    async def gremium_square_logo(self, gremium_id: UUID) -> SquareLogoRef:
        """Return the square logo of the CD variant of a Gremium.

        The caller checks first that the principal may see the Gremium.

        Raises:
            NotFoundError: The Gremium does not exist, holds no variant, or the
                variant holds no square logo (404).
        """
        variant_id = await self.session.scalar(
            select(Gremium.cd_variant_id).where(Gremium.id == gremium_id)
        )
        row: CdVariantLogo | None = None
        if variant_id is not None:
            row = await self.session.scalar(
                select(CdVariantLogo).where(
                    CdVariantLogo.variant_id == variant_id, CdVariantLogo.slot == "square"
                )
            )
        ref = _square_ref(row)
        if ref is None:
            raise NotFoundError(f"gremium {gremium_id} has no logo")
        return ref

    async def square_logo_bytes(self, ref: SquareLogoRef) -> bytes:
        """Load the bytes of a square logo from the object storage.

        Raises:
            ServiceUnavailableError: The object storage is off or unreachable (503).
        """
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        try:
            return await self.storage.get(ref.object_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Could not read CD logo.") from exc

    async def delete_logo(self, logo_id: UUID, actor: str) -> None:
        """Delete a logo entry and its object.

        Raises:
            NotFoundError: No logo has this id (404).
        """
        row = await self.session.get(CdVariantLogo, logo_id)
        if row is None:
            raise NotFoundError(f"cd variant logo {logo_id} not found")
        variant_id = row.variant_id
        object_key = row.object_key
        await self.session.delete(row)
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "cd_variant", variant_id)
        await self.session.commit()
        if object_key is not None:
            await self._remove_object(object_key)

    async def reorder_logos(
        self, variant_id: UUID, payload: CdVariantLogoReorder, actor: str
    ) -> list[CdVariantLogoOut]:
        """Set the order inside one slot. The list must name every logo of that slot.

        Raises:
            NotFoundError: No variant has this id (404).
            ValidationProblem: The list does not match the logos of the slot (422).
        """
        await self._get_or_404(variant_id)
        rows = [
            logo for logo in await self._logos_of(variant_id) if logo.slot == payload.slot
        ]
        by_id = {logo.id: logo for logo in rows}
        if len(payload.logo_ids) != len(rows) or set(payload.logo_ids) != set(by_id):
            raise ValidationProblem(
                "The order must list every logo of the slot exactly once.",
                errors=[{"field": "logoIds", "msg": "does not match the slot"}],
            )
        for position, logo_id in enumerate(payload.logo_ids):
            by_id[logo_id].position = position
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "cd_variant", variant_id)
        await self.session.commit()
        return [_logo_out(by_id[logo_id]) for logo_id in payload.logo_ids]

    async def _by_key(self, key: str) -> CdVariant | None:
        return (
            await self.session.scalars(select(CdVariant).where(CdVariant.key == key))
        ).first()

    async def _get_or_404(self, variant_id: UUID) -> CdVariant:
        row = await self.session.get(CdVariant, variant_id)
        if row is None:
            raise NotFoundError(f"cd variant {variant_id} not found")
        return row

    async def _logos_of(self, variant_id: UUID) -> list[CdVariantLogo]:
        return list(
            (
                await self.session.scalars(
                    select(CdVariantLogo)
                    .where(CdVariantLogo.variant_id == variant_id)
                    .order_by(CdVariantLogo.slot, CdVariantLogo.position, CdVariantLogo.id)
                )
            ).all()
        )

    async def _next_position(self, variant_id: UUID, slot: str) -> int:
        highest = await self.session.scalar(
            select(func.max(CdVariantLogo.position)).where(
                CdVariantLogo.variant_id == variant_id, CdVariantLogo.slot == slot
            )
        )
        return 0 if highest is None else highest + 1

    async def _remove_object(self, object_key: str) -> None:
        """Drop the object after the row is gone. A storage error must not fail the delete."""
        if self.storage is None:
            return
        with contextlib.suppress(StorageError):
            await self.storage.remove(object_key)
