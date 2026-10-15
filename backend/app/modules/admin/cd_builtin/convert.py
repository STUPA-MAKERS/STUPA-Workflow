"""Turn the vendored CD logos into normal uploads (phase 1 of the builtin removal).

``convert_builtin_cd_logos`` uploads the bundled file of every row with
``vendored_name`` into the object storage, under the same key scheme as an
admin upload. It then sets ``object_key``, ``file_name``, ``mime`` and ``size``
and clears ``vendored_name``. Slot and position stay, so a rendered PDF looks
the same. The function also renames a variant whose name is still the seed value
``StuPa`` to ``STUPA``.

The function is idempotent: a second run finds no vendored row and changes
nothing. A transaction-scoped advisory lock lets only one runner work at a time,
because two workers can start together. The other runner returns at once.

Alembic does not run this conversion, because a migration has no object
storage. The arq worker runs it at each start (`worker.cd_builtin`). A new
install gets vendored rows from the seed, and the same job converts them.

Phase 2 (a later release) drops the column ``vendored_name``. This module does
not do that.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import select, text

from app.modules.admin.cd_builtin import BUILTIN_LOGO_MIME, builtin_logo_bytes
from app.modules.admin.models import CdVariant, CdVariantLogo
from app.modules.admin.service.cd_variants import CD_LOGO_PREFIX
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.shared.errors import ServiceUnavailableError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.files.storage import ObjectStorage

logger = logging.getLogger("app.admin.cd_builtin")

# Fixed advisory-lock key of the conversion. It is a constant, not user input.
_LOCK_KEY: Final[int] = 0x43445F4255494C54  # "CD_BUILT"
SYSTEM_ACTOR: Final[str] = "system"
SEED_NAME: Final[str] = "StuPa"
NEW_NAME: Final[str] = "STUPA"


@dataclass(frozen=True, slots=True)
class BuiltinConversion:
    """The result of one run.

    Attributes:
        skipped: Another runner holds the lock, so this run changed nothing.
        logos: How many rows became uploads.
        variants: How many variants got an audit entry.
        renamed: How many variants changed their name from ``StuPa`` to ``STUPA``.
    """

    skipped: bool = False
    logos: int = 0
    variants: int = 0
    renamed: int = 0


async def convert_builtin_cd_logos(
    session: AsyncSession, storage: ObjectStorage | None
) -> BuiltinConversion:
    """Convert every vendored logo row into an upload and commit.

    A row whose name the manifest does not hold stays as it is, with a warning.
    The render service still ships that file, so its PDFs do not change.

    Raises:
        ServiceUnavailableError: A row needs a conversion, but the object storage
            is off.
        StorageError: An upload failed. Nothing is committed. The objects that
            went up before stay in the bucket as orphans, which is harmless.
        BuiltinLogoMismatchError: A bundled file differs from its pinned hash.
    """
    locked = await session.scalar(text(f"SELECT pg_try_advisory_xact_lock({_LOCK_KEY})"))
    if not locked:
        return BuiltinConversion(skipped=True)

    rows = (
        await session.scalars(
            select(CdVariantLogo)
            .where(CdVariantLogo.vendored_name.is_not(None))
            .order_by(CdVariantLogo.variant_id, CdVariantLogo.slot, CdVariantLogo.position)
            .with_for_update()
        )
    ).all()
    seed_named = (
        await session.scalars(
            select(CdVariant).where(CdVariant.name == SEED_NAME).with_for_update()
        )
    ).all()
    if not rows and not seed_named:
        return BuiltinConversion()

    converted: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        name = row.vendored_name or ""
        bundled = builtin_logo_bytes(name)
        if bundled is None:
            logger.warning("cd logo %s: no bundled file for %r, row stays vendored", row.id, name)
            continue
        if storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        entry, data = bundled
        object_key = f"{CD_LOGO_PREFIX}{uuid.uuid4().hex}/{entry.file_name}"
        await storage.put(object_key, data, BUILTIN_LOGO_MIME)
        row.object_key = object_key
        row.file_name = entry.file_name
        row.mime = BUILTIN_LOGO_MIME
        row.size = len(data)
        row.vendored_name = None
        converted[row.variant_id].append(
            {"logoId": str(row.id), "slot": row.slot, "vendoredName": name}
        )

    renamed = {variant.id: variant for variant in seed_named}
    for variant in renamed.values():
        variant.name = NEW_NAME

    for variant_id in sorted({*converted, *renamed}, key=str):
        data_out: dict[str, Any] = {"reason": "builtin_cd_logos_converted"}
        if variant_id in converted:
            data_out["convertedLogos"] = converted[variant_id]
        if variant_id in renamed:
            data_out["renamed"] = {"old": SEED_NAME, "new": NEW_NAME}
        await audit_record(
            session,
            actor=SYSTEM_ACTOR,
            action=AuditAction.CONFIG_CHANGE,
            target_type="cd_variant",
            target_id=str(variant_id),
            data=data_out,
        )
    await session.commit()
    return BuiltinConversion(
        logos=sum(len(items) for items in converted.values()),
        variants=len({*converted, *renamed}),
        renamed=len(renamed),
    )
