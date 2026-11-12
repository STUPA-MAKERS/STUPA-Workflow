"""Routes of the observers of an application.

- ``GET``, ``POST`` and ``DELETE .../observers`` list, add and remove the observers.
  Only the applicant session of the application, the logged-in creator and a holder of
  ``application.manage`` pass (`observers.can_manage_observers`); everybody else gets
  403. An add sends the observer one mail after the commit.
- ``POST /observers/end`` ends an observation with the token of the end link of a mail.
  It needs no login, because the observer may have no account. An unknown or invalid
  token answers 404.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status

from app.db import get_sessionmaker
from app.deps import DbSession, SettingsDep
from app.modules.applications.access import Access, require_app_read
from app.modules.applications.observer_mails import notify_observer_added
from app.modules.applications.observers import (
    add_observer,
    can_manage_observers,
    end_observation,
    is_creator,
    list_observers,
    remove_observer,
)
from app.modules.applications.schemas import ObserverCreate, ObserverEnd, ObserverOut
from app.modules.notifications.provider import mail_queue_from_pool
from app.settings import Settings
from app.shared.errors import ForbiddenError

logger = logging.getLogger("app.notifications")

router = APIRouter(tags=["applications"])

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"description": "problem+json"} for code in (401, 403, 404, 409, 422)
}


async def require_observer_manager(
    db: DbSession, access: Annotated[Access, Depends(require_app_read)]
) -> Access:
    """Grant the management of the observers (see `can_manage_observers`).

    Raises:
        ForbiddenError: The caller reads the application but is not its applicant and
            holds no ``application.manage``.
    """
    creator = access.principal is not None and await is_creator(
        db, access.application_id, access.principal.sub
    )
    if not can_manage_observers(access, is_creator=creator):
        raise ForbiddenError("Only the applicant manages the observers.")
    return access


ManagerDep = Annotated[Access, Depends(require_observer_manager)]


async def _deliver_added_mail(
    settings: Settings, application_id: UUID, observer_id: UUID, pool: object
) -> None:
    """Send the mail to a new observer (background task, own session, best effort)."""
    try:
        async with get_sessionmaker()() as session:
            await notify_observer_added(
                session,
                queue=mail_queue_from_pool(pool),  # type: ignore[arg-type]
                settings=settings,
                application_id=application_id,
                observer_id=observer_id,
            )
            await session.commit()
    except Exception:
        logger.exception("observer mail failed (application=%s)", application_id)


ObserverMailSender = Callable[[Settings, UUID, UUID, object], Awaitable[None]]


def get_observer_mail_sender() -> ObserverMailSender:
    """Return the injectable sender of the observer mail that a test can override."""
    return _deliver_added_mail


@router.get(
    "/applications/{application_id}/observers",
    response_model=list[ObserverOut],
    responses=_ERRORS,
)
async def get_observers(db: DbSession, access: ManagerDep) -> list[ObserverOut]:
    """List the observers of an application, the oldest first."""
    rows = await list_observers(db, access.application_id)
    return [ObserverOut(id=r.id, email=r.email, addedAt=r.added_at) for r in rows]


@router.post(
    "/applications/{application_id}/observers",
    response_model=ObserverOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def post_observer(
    payload: ObserverCreate,
    db: DbSession,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    access: ManagerDep,
    send_mail: Annotated[ObserverMailSender, Depends(get_observer_mail_sender)],
) -> ObserverOut:
    """Add an observer by e-mail address and send it one mail after the commit.

    An application has at most five observers (422 ``observer_limit``). The applicant
    address is refused (422 ``observer_is_applicant``), an address that observes
    already answers 409 ``observer_exists``. The answer is the same for an address with
    and without an account.
    """
    row = await add_observer(db, access.application_id, str(payload.email), actor=access.actor)
    out = ObserverOut(id=row.id, email=row.email, addedAt=row.added_at)
    await db.commit()
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(send_mail, settings, access.application_id, out.id, pool)
    return out


@router.delete(
    "/applications/{application_id}/observers/{observer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
)
async def delete_observer(observer_id: UUID, db: DbSession, access: ManagerDep) -> Response:
    """Remove an observer. The next request of the observer gets 403."""
    await remove_observer(db, access.application_id, observer_id, actor=access.actor)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/observers/end",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "problem+json"}, 422: {"description": "problem+json"}},
)
async def post_end_observation(
    payload: ObserverEnd, db: DbSession, settings: SettingsDep
) -> Response:
    """End an observation with the token of the end link of a mail, without a login."""
    await end_observation(db, settings.magic_link_secret, payload.token)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
