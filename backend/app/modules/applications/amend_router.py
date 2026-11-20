"""Route of a later change of the approved amount (spec 001620).

`POST /applications/{id}/approved-amount` needs `application.amend_decision` and the
read right on the application (`resolve_app_read`), as the flow routes do. The route
commits the new decision and then mails the applicant in the background.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.db import get_sessionmaker
from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.applications.access import resolve_app_read
from app.modules.applications.amend import AmendIn, AmendOut, amend_approved_amount
from app.modules.applications.amend_mail import send_amount_changed_mail
from app.modules.notifications.provider import mail_queue_from_pool
from app.settings import Settings
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["applications"])

#: Change the approved amount of an approved application.
AMEND_PERMISSION = "application.amend_decision"

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


async def require_amend_principal(
    application_id: UUID,
    db: DbSession,
    principal: Annotated[Principal, Depends(require_principal(AMEND_PERMISSION))],
) -> Principal:
    """Admit a principal with `application.amend_decision` who can read the application."""
    await resolve_app_read(db, application_id, principal, None)
    return principal


async def _deliver(
    settings: Settings, application_id: UUID, out: AmendOut, payload: AmendIn, pool: object
) -> None:
    """Send the mail to the applicant in an own session, after the answer."""
    async with get_sessionmaker()() as db:
        await send_amount_changed_mail(
            db,
            queue=mail_queue_from_pool(pool),  # type: ignore[arg-type]
            settings=settings,
            application_id=application_id,
            previous=out.previous_amount,
            approved=out.approved_amount,
            gremium_id=payload.gremium_id,
            decision_date=payload.decision_date,
        )


@router.post(
    "/applications/{application_id}/approved-amount",
    response_model=AmendOut,
    responses=dict.fromkeys((400, 401, 403, 404, 409, 422), _PROBLEM),
)
async def amend_amount(
    application_id: UUID,
    payload: AmendIn,
    db: DbSession,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    principal: Annotated[Principal, Depends(require_amend_principal)],
) -> AmendOut:
    """Change the approved amount of an approved application; the state stays.

    The route gives 409 `application_not_approved` outside an approved state and 422
    for a bad amount, the same amount, a decision date after today or an unknown
    Gremium. The amount may be above the requested amount.
    """
    out = await amend_approved_amount(
        db, application_id, payload, actor=principal.sub, now=datetime.now(UTC)
    )
    await db.commit()
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(_deliver, settings, application_id, out, payload, pool)
    return out
