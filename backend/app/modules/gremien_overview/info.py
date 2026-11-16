"""The Info tab of a Gremium: read for everyone who sees it, save with ``info.write``.

The read gate (``require_gremium``) runs in the router. The save needs the gremium
permission ``info.write`` from the own gremium role, without the admin bypass, because a
gremium right comes only from the membership. A save sends the version that the editor
read: an older version gives 409 ``gremium_info_version_conflict``, so two editors do
not overwrite each other unseen. Each save writes one ``gremium_info_update`` audit entry
with counts only, never the text or a link.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.policy import holds_gremium_permission
from app.modules.auth.principal import Principal
from app.modules.gremien.models import GremiumInfo
from app.modules.gremien_overview.schemas import GremiumInfoIn, GremiumInfoLink, GremiumInfoOut
from app.shared.errors import ConflictError, ForbiddenError

INFO_WRITE: Final = "info.write"
VERSION_CONFLICT: Final = "gremium_info_version_conflict"


async def _editor_name(db: AsyncSession, principal_id: UUID | None) -> str | None:
    """Return the display name of the last editor, ``None`` without one."""
    if principal_id is None:
        return None
    return (
        await db.execute(select(PrincipalRow.display_name).where(PrincipalRow.id == principal_id))
    ).scalar_one_or_none()


async def _out(db: AsyncSession, row: GremiumInfo | None, *, can_edit: bool) -> GremiumInfoOut:
    """Build the answer from the row, or the empty Info without a row."""
    if row is None:
        return GremiumInfoOut(
            body_md="",
            links=(),
            version=0,
            updated_at=None,
            updated_by_name=None,
            can_edit=can_edit,
        )
    return GremiumInfoOut(
        body_md=row.body_md,
        links=tuple(GremiumInfoLink.model_validate(link) for link in row.links),
        version=row.version,
        updated_at=row.updated_at,
        updated_by_name=await _editor_name(db, row.updated_by),
        can_edit=can_edit,
    )


async def read_info(db: AsyncSession, principal: Principal, gremium_id: UUID) -> GremiumInfoOut:
    """Return the Info of a Gremium that the caller sees, with ``canEdit``."""
    row = await db.get(GremiumInfo, gremium_id)
    can_edit = await holds_gremium_permission(db, principal, INFO_WRITE, gremium_id)
    return await _out(db, row, can_edit=can_edit)


async def save_info(
    db: AsyncSession, principal: Principal, gremium_id: UUID, body: GremiumInfoIn
) -> GremiumInfoOut:
    """Save text and links together and write the audit entry, without a commit.

    Raises:
        ForbiddenError: The caller does not hold ``info.write`` in the Gremium (403).
        ConflictError: ``version`` is not the stored version (409
            ``gremium_info_version_conflict``).
    """
    if not await holds_gremium_permission(db, principal, INFO_WRITE, gremium_id):
        raise ForbiddenError("not allowed to edit the info of this gremium")
    row = (
        await db.execute(
            select(GremiumInfo).where(GremiumInfo.gremium_id == gremium_id).with_for_update()
        )
    ).scalar_one_or_none()
    stored = 0 if row is None else row.version
    if body.version != stored:
        raise ConflictError("the info changed since it was read", code=VERSION_CONFLICT)
    editor_id = (
        await db.execute(select(PrincipalRow.id).where(PrincipalRow.sub == principal.sub))
    ).scalar_one_or_none()
    values = {
        "body_md": body.body_md,
        "links": [link.model_dump() for link in body.links],
        "version": stored + 1,
        "updated_at": datetime.now(UTC),
        "updated_by": editor_id,
    }
    upsert = (
        pg_insert(GremiumInfo)
        .values(gremium_id=gremium_id, **values)
        .on_conflict_do_update(index_elements=[GremiumInfo.gremium_id], set_=values)
        .returning(GremiumInfo)
        .execution_options(populate_existing=True)
    )
    target = (await db.execute(upsert)).scalar_one()
    await audit_record(
        db,
        actor=principal.sub,
        action=AuditAction.GREMIUM_INFO_UPDATE,
        target_type="gremium",
        target_id=str(gremium_id),
        data={
            "gremiumId": str(gremium_id),
            "version": target.version,
            "textLength": len(body.body_md),
            "links": len(body.links),
        },
    )
    return await _out(db, target, can_edit=True)
