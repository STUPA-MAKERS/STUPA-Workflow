"""The read of a status list for each signed-in member (F/administration/admin/003040).

Each page that shows an element reads the names, the tones and the phases of its list
here. The admin routes that change a list live in the module ``admin``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import DbSession, Principal, require_principal
from app.modules.statuses.schemas import StatusList, StatusListOut
from app.modules.statuses.service import StatusReader
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/statuses", tags=["statuses"])

Member = Annotated[Principal, Depends(require_principal())]


@router.get(
    "/{kind}",
    response_model=StatusListOut,
    responses={401: {"model": ProblemDetail}, 422: {"model": ProblemDetail}},
)
async def status_list(kind: StatusList, session: DbSession, _principal: Member) -> StatusListOut:
    """Return the status list of an element kind in its order."""
    return await StatusReader(session).out(kind)
