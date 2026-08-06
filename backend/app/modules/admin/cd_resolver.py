"""Resolve the corporate design of a Gremium for the render path.

This module is the seam between the admin CRUD and the PDF renderers. It turns
the ``cd_variant`` rows of a Gremium into the two logo tuples that pytex expects
plus the asset bytes that go with them.

A vendored logo contributes only its name (``INF``, ``MAKERS``, ...). pytex ships
that file. An uploaded logo contributes a plain asset file name to the tuple AND
its bytes to ``assets``. The caller writes those bytes next to the document
before the render, under exactly the returned name. The name holds no path
separator, because pytex refuses one, and it carries the logo row id, so two
uploads of the same original name never collide.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.modules.admin.cd_logos import CdBaseVariant, asset_file_name
from app.modules.admin.models import CdVariant, CdVariantLogo, Gremium
from app.modules.files.storage import StorageError
from app.shared.errors import ServiceUnavailableError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.files.storage import ObjectStorage


@dataclass(frozen=True, slots=True)
class ResolvedCdVariant:
    """The corporate design of one Gremium, ready for a pytex render.

    Attributes:
        base_variant: The pytex document shape, ``report`` or ``protocol``.
        title_logos: Title-page logos in order — vendored names AND/OR asset
            file names.
        footer_logos: Footer logos in the same value form.
        assets: Asset file name to bytes, loaded from the object storage. A
            vendored logo has no entry here.
    """

    base_variant: CdBaseVariant
    title_logos: tuple[str, ...]
    footer_logos: tuple[str, ...]
    assets: Mapping[str, bytes]


async def cd_variant_key_for_gremium(db: AsyncSession, gremium: Gremium | None) -> str | None:
    """Return the CD-variant key of a Gremium.

    Returns:
        The ``cd_variant.key``, or ``None`` when the Gremium is missing or holds
        no variant.
    """
    if gremium is None or gremium.cd_variant_id is None:
        return None
    return await db.scalar(select(CdVariant.key).where(CdVariant.id == gremium.cd_variant_id))


async def resolve_cd_variant(
    db: AsyncSession, storage: ObjectStorage | None, gremium_id: UUID | None
) -> ResolvedCdVariant | None:
    """Resolve the corporate design that a Gremium renders with.

    Returns:
        The resolved variant, or ``None`` when the Gremium does not exist, holds
        no variant, or the referenced variant is gone.

    Raises:
        ServiceUnavailableError: The variant holds an uploaded logo, but the
            object storage is off or unreachable. The render must fail loudly
            instead of producing a document with a missing logo.
    """
    if gremium_id is None:
        return None
    variant_id = await db.scalar(
        select(Gremium.cd_variant_id).where(Gremium.id == gremium_id)
    )
    if variant_id is None:
        return None
    variant = await db.get(CdVariant, variant_id)
    if variant is None:  # pragma: no cover - the FK is RESTRICT, so this cannot happen
        return None

    rows = (
        await db.scalars(
            select(CdVariantLogo)
            .where(CdVariantLogo.variant_id == variant_id)
            .order_by(CdVariantLogo.slot, CdVariantLogo.position, CdVariantLogo.id)
        )
    ).all()

    logos: dict[str, list[str]] = {"title": [], "footer": []}
    assets: dict[str, bytes] = {}
    for row in rows:
        if row.vendored_name is not None:
            logos[row.slot].append(row.vendored_name)
            continue
        name = asset_file_name(row.id, row.file_name, row.mime or "")
        assets[name] = await _load_asset(storage, row.object_key)
        logos[row.slot].append(name)

    return ResolvedCdVariant(
        base_variant=_base_variant(variant.base_variant),
        title_logos=tuple(logos["title"]),
        footer_logos=tuple(logos["footer"]),
        assets=assets,
    )


def _base_variant(value: str) -> CdBaseVariant:
    """Narrow the stored text to the closed set. The DB check holds the invariant."""
    return "protocol" if value == "protocol" else "report"


async def _load_asset(storage: ObjectStorage | None, object_key: str | None) -> bytes:
    if storage is None or object_key is None:
        raise ServiceUnavailableError("Object storage unavailable.")
    try:
        return await storage.get(object_key)
    except StorageError as exc:
        raise ServiceUnavailableError("Could not read CD logo.") from exc
