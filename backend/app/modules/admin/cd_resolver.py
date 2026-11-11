"""Resolve the corporate design of a Gremium for the render path.

This module is the seam between the admin CRUD and the PDF renderers. It turns
the ``cd_variant`` rows of a Gremium into the two logo tuples that the render
service expects
plus the asset bytes that go with them.

A vendored logo contributes only its name (``INF``, ``MAKERS``, ...). The render service ships
that file. An uploaded logo contributes a plain asset file name to the tuple AND
its bytes to ``assets``. The caller writes those bytes next to the document
before the render, under exactly the returned name. The name holds no path
separator, because the render service refuses one, and it carries the logo row id, so two
uploads of the same original name never collide.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.modules.admin.cd_logos import RENDER_SLOTS, asset_file_name
from app.modules.admin.models import CdVariant, CdVariantLogo
from app.modules.files.storage import StorageError
from app.modules.gremien.models import Gremium
from app.shared.errors import ServiceUnavailableError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.files.storage import ObjectStorage


@dataclass(frozen=True, slots=True)
class ResolvedCdVariant:
    """The corporate design of one Gremium, ready for a render.

    A design contributes LOGOS. It does not decide what kind of document is being
    rendered: one Gremium renders applications and protocols, so the shape belongs to
    the render path, which pins its own.

    Attributes:
        title_logos: Title-page logos in order — vendored names AND/OR asset
            file names.
        footer_logos: Footer logos in the same value form.
        assets: Asset file name to bytes, loaded from the object storage. A
            vendored logo has no entry here.
    """

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


async def resolve_cd_variant_by_key(
    db: AsyncSession, storage: ObjectStorage | None, key: str | None
) -> ResolvedCdVariant | None:
    """Resolve a corporate design by its key.

    A protocol snapshots the key of its Gremium when it is created, so the
    document keeps its design even after the Gremium moves to another one. That
    path must resolve the snapshot, never the Gremium of today.

    Returns:
        The resolved variant, or ``None`` when no key is given or no variant
        carries it.

    Raises:
        ServiceUnavailableError: The variant holds an uploaded logo and the
            object storage is off or unreachable.
    """
    if key is None:
        return None
    variant = await db.scalar(select(CdVariant).where(CdVariant.key == key))
    if variant is None:
        return None
    return await _resolve(db, storage, variant)


async def _resolve(
    db: AsyncSession, storage: ObjectStorage | None, variant: CdVariant
) -> ResolvedCdVariant:
    """Load the logo rows of a variant and turn them into names plus bytes.

    Only the render slots count. The square logo belongs to the app, so its row is
    filtered out in the query and skipped again in the comprehension.
    """
    variant_id = variant.id
    rows = (
        await db.scalars(
            select(CdVariantLogo)
            .where(
                CdVariantLogo.variant_id == variant_id,
                CdVariantLogo.slot.in_(RENDER_SLOTS),
            )
            .order_by(CdVariantLogo.slot, CdVariantLogo.position, CdVariantLogo.id)
        )
    ).all()

    entries = [
        (row.slot, await _logo_entry(storage, row)) for row in rows if row.slot in RENDER_SLOTS
    ]
    return ResolvedCdVariant(
        title_logos=tuple(name for slot, (name, _) in entries if slot == "title"),
        footer_logos=tuple(name for slot, (name, _) in entries if slot == "footer"),
        assets={name: data for _, (name, data) in entries if data is not None},
    )


async def _logo_entry(
    storage: ObjectStorage | None, row: CdVariantLogo
) -> tuple[str, bytes | None]:
    """Return the tuple value of one logo row and its asset bytes.

    A vendored logo gives its name and no bytes, because the render service ships the
    file. An uploaded logo gives its asset file name and the bytes from the storage.
    """
    if row.vendored_name is not None:
        return row.vendored_name, None
    name = asset_file_name(row.id, row.file_name, row.mime or "")
    return name, await _load_asset(storage, row.object_key)


def cd_render_config(cd: ResolvedCdVariant) -> dict[str, object]:
    """Return the render `config` object that carries the logos of a design.

    The renderer reads the keys `logos` and `footer_logos`. An empty tuple stays out of
    the object, because an empty list would override the default of the document
    shape with nothing instead of leaving it alone.
    """
    return {
        **({"logos": list(cd.title_logos)} if cd.title_logos else {}),
        **({"footer_logos": list(cd.footer_logos)} if cd.footer_logos else {}),
    }


async def _load_asset(storage: ObjectStorage | None, object_key: str | None) -> bytes:
    if storage is None or object_key is None:
        raise ServiceUnavailableError("Object storage unavailable.")
    try:
        return await storage.get(object_key)
    except StorageError as exc:
        raise ServiceUnavailableError("Could not read CD logo.") from exc
