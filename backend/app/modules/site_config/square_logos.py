"""Which gremien show a square logo, and the path of that logo.

A gremium shows the square logo of its CD variant. The rule matches the one of the logo
route ``GET /api/committees/{id}/logo`` (``_square_ref``): the variant has a stored raster
logo in the ``square`` slot. Lists that show a gremium with its logo (the overview, the
meeting filter, the member entries of a to-do board) give the path only for such a
gremium, so the browser never asks for a logo that answers 404.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_config.cd_logos import ALLOWED_SQUARE_LOGO_MIME
from app.modules.site_config.models import CdVariantLogo

#: The slot of the square logo of a CD variant.
SQUARE_SLOT = "square"


def gremium_logo_url(gremium_id: UUID) -> str:
    """Return the API path of the square logo of a gremium."""
    return f"/api/committees/{gremium_id}/logo"


async def square_logo_variants(
    session: AsyncSession, variant_ids: Iterable[UUID | None]
) -> frozenset[UUID]:
    """Return the CD variants of ``variant_ids`` that hold a stored raster square logo."""
    wanted = {v for v in variant_ids if v is not None}
    if not wanted:
        return frozenset()
    rows = await session.scalars(
        select(CdVariantLogo.variant_id)
        .where(
            CdVariantLogo.variant_id.in_(wanted),
            CdVariantLogo.slot == SQUARE_SLOT,
            CdVariantLogo.object_key.is_not(None),
            CdVariantLogo.mime.in_(sorted(ALLOWED_SQUARE_LOGO_MIME)),
        )
        .distinct()
    )
    return frozenset(rows.all())


def logo_url_of(gremium_id: UUID, variant_id: UUID | None, logos: frozenset[UUID]) -> str | None:
    """Return the logo path of a gremium whose variant is in ``logos``, else None."""
    return gremium_logo_url(gremium_id) if variant_id in logos else None
