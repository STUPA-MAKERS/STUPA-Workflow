"""The public read of a status list (F/administration/admin/003035).

Each page that shows an element reads the names, the tones and the phases of its list
here, also the applicant view of a magic-link session. A list is plain config without
personal data, so the read needs no login. The admin routes that change a list live in
the module ``admin``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import DbSession
from app.modules.statuses.schemas import StatusList, StatusListOut
from app.modules.statuses.service import StatusReader
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/statuses", tags=["statuses"])


@router.get(
    "/{kind}",
    response_model=StatusListOut,
    responses={422: {"model": ProblemDetail}},
)
async def status_list(kind: StatusList, session: DbSession) -> StatusListOut:
    """Return the status list of an element kind in its order."""
    return await StatusReader(session).out(kind)
