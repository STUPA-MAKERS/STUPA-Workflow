"""Admin routes of the status lists: the page "Status & Phasen" (/admin/statuses).

The page needs ``admin.statuses`` (F/administration/admin/003035). The read of a list for
each member is ``GET /api/statuses/{kind}`` in the module ``statuses``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import DbSession, Principal, require_principal
from app.modules.admin.router.deps import _errors
from app.modules.admin.service.statuses import StatusListAdmin
from app.modules.statuses.schemas import StatusList, StatusListOut, StatusListSet

router = APIRouter(prefix="/admin", tags=["admin"])

StatusAdmin = Annotated[Principal, Depends(require_principal("admin.statuses"))]


@router.get("/statuses/{kind}", response_model=StatusListOut, responses=_errors(401, 403, 422))
async def get_status_list(
    kind: StatusList, session: DbSession, _principal: StatusAdmin
) -> StatusListOut:
    """Return a status list with the number of elements of each status."""
    return await StatusListAdmin(session).get(kind)


@router.put("/statuses/{kind}", response_model=StatusListOut, responses=_errors(401, 403, 409, 422))
async def set_status_list(
    kind: StatusList, payload: StatusListSet, session: DbSession, principal: StatusAdmin
) -> StatusListOut:
    """Replace a status list; a removed status in use needs a replacement (003038)."""
    out = await StatusListAdmin(session).save(kind, payload, principal.sub)
    await session.commit()
    return out
