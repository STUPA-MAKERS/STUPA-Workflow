"""CRUD for the corporate-design variants and their logos (`admin.cd_variants`).

Every mutation writes an audit entry in the same transaction as the change.
The upload path decides the type from the magic bytes and allows PDF, so the
download path must force an attachment disposition — see
`app.modules.admin.router.get_cd_variant_logo_file`.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.modules.admin.cd_logos import (
    ALLOWED_CD_LOGO_MIME,
    MAX_CD_LOGO_BYTES,
    MAX_CD_LOGO_TOTAL_BYTES,
    MAX_CD_LOGOS_PER_VARIANT,
    LogoSlot,
    sniff_cd_logo,
)
from app.modules.admin.models import CdVariant, CdVariantLogo, Gremium
from app.modules.admin.schemas import (
    CdVariantCreate,
    CdVariantLogoOut,
    CdVariantLogoReorder,
    CdVariantLogoUpdate,
    CdVariantLogoVendoredCreate,
    CdVariantOptionOut,
    CdVariantOut,
    CdVariantUpdate,
)
from app.modules.admin.service.service_base import ConfigServiceBase
from app.modules.audit.actions import AuditAction
from app.modules.files.mime import sanitize_filename
from app.modules.files.storage import StorageError
from app.modules.protocol.models import Protocol
from app.shared.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
    ValidationProblem,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.files.storage import ObjectStorage

CD_LOGO_PREFIX = "cd-logos/"


def _logo_out(row: CdVariantLogo) -> CdVariantLogoOut:
    return CdVariantLogoOut(
        id=row.id,
        slot="footer" if row.slot == "footer" else "title",
        position=row.position,
        vendored_name=row.vendored_name,
        file_name=row.file_name,
        mime=row.mime,
        size=row.size,
    )


def _variant_out(row: CdVariant, logos: list[CdVariantLogo]) -> CdVariantOut:
    return CdVariantOut(
        id=row.id,
        key=row.key,
        name=row.name,
        base_variant="protocol" if row.base_variant == "protocol" else "report",
        logos=[_logo_out(logo) for logo in logos],
    )


class CdVariantService(ConfigServiceBase):
    """Corporate-design variants: CRUD, logo upload, vendored logos, ordering."""

    def __init__(self, session: AsyncSession, *, storage: ObjectStorage | None = None) -> None:
        super().__init__(session)
        self.storage = storage

    # --- variants ---------------------------------------------------------

    async def list_variants(self) -> list[CdVariantOut]:
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
        """Patch the display name.

        Raises:
            NotFoundError: No variant has this id (404).
            ConflictError: The payload tries to change the immutable key (409).
        """
        row = await self._get_or_404(variant_id)
        if payload.key is not None and payload.key != row.key:
            raise ConflictError("cd variant key is immutable", code="cd_variant_key_immutable")
        if payload.name is not None:
            row.name = payload.name
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "cd_variant", row.id)
        await self.session.commit()
        return _variant_out(row, await self._logos_of(row.id))

    async def delete_variant(self, variant_id: UUID, actor: str) -> None:
        """Delete a variant and its logos.

        Raises:
            NotFoundError: No variant has this id (404).
            ConflictError: A Gremium or a protocol still references the variant (409).
        """
        row = await self._get_or_404(variant_id)
        in_use = await self.session.scalar(
            select(Gremium.id).where(Gremium.cd_variant_id == variant_id).limit(1)
        )
        if in_use is not None:
            raise ConflictError(
                "cd variant is still referenced by a gremium",
                code="cd_variant_in_use_gremium",
            )
        # A protocol snapshots the KEY without a foreign key. A deleted variant
        # would silently fall back to auto-detect on the next render.
        snapshot = await self.session.scalar(
            select(Protocol.id).where(Protocol.cd_variant == row.key).limit(1)
        )
        if snapshot is not None:
            raise ConflictError(
                "cd variant is still referenced by a protocol",
                code="cd_variant_in_use_protocol",
            )
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

    # --- logos ------------------------------------------------------------

    async def add_vendored_logo(
        self, variant_id: UUID, payload: CdVariantLogoVendoredCreate, actor: str
    ) -> CdVariantLogoOut:
        """Add a logo that pytex ships.

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

        Raises:
            NotFoundError: No variant has this id (404).
            PayloadTooLargeError: The bytes exceed the cap (413).
            ConflictError: The variant already holds the maximum number of
                uploaded logos, or the upload would push their total size over
                the cap (409).
            UnsupportedMediaTypeError: The magic bytes are not one of the
                accepted types (415).
            ServiceUnavailableError: The object storage is off or the write
                failed (503).
        """
        await self._get_or_404(variant_id)
        if len(data) > MAX_CD_LOGO_BYTES:
            raise PayloadTooLargeError(f"Logo exceeds {MAX_CD_LOGO_BYTES} bytes.")
        if not data:
            raise UnsupportedMediaTypeError("Empty file.")
        mime = sniff_cd_logo(data)
        if mime is None or mime not in ALLOWED_CD_LOGO_MIME:
            raise UnsupportedMediaTypeError(
                "Logo must be PNG, JPEG, WebP or PDF (checked from the bytes)."
            )
        await self._assert_upload_budget(variant_id, len(data))
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        safe_name = sanitize_filename(filename)
        object_key = f"{CD_LOGO_PREFIX}{uuid.uuid4().hex}/{safe_name}"
        try:
            await self.storage.put(object_key, data, mime)
        except StorageError as exc:
            raise ServiceUnavailableError("Object storage write failed.") from exc
        row = CdVariantLogo(
            variant_id=variant_id,
            slot=slot,
            position=await self._next_position(variant_id, slot),
            object_key=object_key,
            file_name=safe_name,
            mime=mime,
            size=len(data),
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "cd_variant", variant_id)
        await self.session.commit()
        return _logo_out(row)

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

    async def update_logo(
        self, logo_id: UUID, payload: CdVariantLogoUpdate, actor: str
    ) -> CdVariantLogoOut:
        """Move a logo to another slot or to another place inside its slot.

        The stored bytes and the file name stay untouched. Both the source and
        the target slot come out densely numbered from 0.

        Raises:
            NotFoundError: No logo has this id (404).
        """
        row = await self.session.get(CdVariantLogo, logo_id)
        if row is None:
            raise NotFoundError(f"cd variant logo {logo_id} not found")
        source_slot = row.slot
        target_slot: LogoSlot = payload.slot or ("footer" if source_slot == "footer" else "title")
        others = [
            logo for logo in await self._logos_of(row.variant_id) if logo.id != row.id
        ]
        siblings = [logo for logo in others if logo.slot == target_slot]
        if payload.position is not None:
            index = min(payload.position, len(siblings))
        elif target_slot == source_slot:
            index = min(row.position, len(siblings))
        else:
            index = len(siblings)
        row.slot = target_slot
        for position, logo in enumerate([*siblings[:index], row, *siblings[index:]]):
            logo.position = position
        if target_slot != source_slot:
            for position, logo in enumerate(
                [logo for logo in others if logo.slot == source_slot]
            ):
                logo.position = position
        await self._audit(actor, AuditAction.CONFIG_CHANGE, "cd_variant", row.variant_id)
        await self.session.commit()
        return _logo_out(row)

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

    # --- helpers ----------------------------------------------------------

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

    async def _assert_upload_budget(self, variant_id: UUID, incoming: int) -> None:
        """Check the uploaded logos of a variant against the pytex asset budget.

        A vendored logo travels as a name and carries no asset, so it does not count.

        Raises:
            ConflictError: The count cap or the aggregate size cap is reached (409).
        """
        count, total = (
            await self.session.execute(
                select(
                    func.count(CdVariantLogo.id),
                    func.coalesce(func.sum(CdVariantLogo.size), 0),
                ).where(
                    CdVariantLogo.variant_id == variant_id,
                    CdVariantLogo.object_key.is_not(None),
                )
            )
        ).one()
        if count >= MAX_CD_LOGOS_PER_VARIANT:
            raise ConflictError(
                f"A variant carries at most {MAX_CD_LOGOS_PER_VARIANT} uploaded logos.",
                code="cd_logo_count_limit",
            )
        if total + incoming > MAX_CD_LOGO_TOTAL_BYTES:
            raise ConflictError(
                f"The uploaded logos of a variant must stay under "
                f"{MAX_CD_LOGO_TOTAL_BYTES} bytes in total.",
                code="cd_logo_total_limit",
            )

    async def _next_position(self, variant_id: UUID, slot: str) -> int:
        highest = await self.session.scalar(
            select(func.max(CdVariantLogo.position)).where(
                CdVariantLogo.variant_id == variant_id, CdVariantLogo.slot == slot
            )
        )
        return 0 if highest is None else highest + 1

    async def _remove_object(self, object_key: str) -> None:
        """Drop the object after the row is gone; an orphan object must not fail the delete."""
        if self.storage is None:
            return
        with contextlib.suppress(StorageError):
            await self.storage.remove(object_key)
