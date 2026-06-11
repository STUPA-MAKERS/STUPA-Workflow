"""Notifications-API-Router (#4-2, api.md »notifications«).

* ``GET /api/notifications/preferences`` — eigene Benachrichtigungs-Schalter
  (voller Katalog, Default aktiviert).
* ``PUT /api/notifications/preferences`` — Bulk-Update der eigenen Schalter.

Beide Endpunkte verlangen nur einen eingeloggten Principal (keine besondere
Permission): jede:r verwaltet ausschließlich die eigenen Einstellungen.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.deps import DbSession, Principal, require_principal
from app.modules.notifications.schemas import (
    NotificationPreferenceOut,
    NotificationPreferencesUpdate,
)
from app.modules.notifications.service import NotificationService
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/notifications", tags=["notifications"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_AUTH_ERRORS: dict[int | str, dict[str, Any]] = {401: _PROBLEM, 403: _PROBLEM}


def get_notification_service(session: DbSession) -> NotificationService:
    return NotificationService(session)


ServiceDep = Annotated[NotificationService, Depends(get_notification_service)]
PrincipalDep = Annotated[Principal, Depends(require_principal())]


@router.get(
    "/preferences",
    response_model=list[NotificationPreferenceOut],
    responses=_AUTH_ERRORS,
)
async def get_preferences(
    service: ServiceDep, principal: PrincipalDep
) -> list[NotificationPreferenceOut]:
    """Eigene Schalter lesen (voller Katalog; kein Eintrag = aktiviert)."""
    prefs = await service.get_preferences(principal.sub)
    return [NotificationPreferenceOut(kind=k, enabled=e) for k, e in prefs]


@router.put(
    "/preferences",
    response_model=list[NotificationPreferenceOut],
    responses={**_AUTH_ERRORS, 404: _PROBLEM, 422: _PROBLEM},
)
async def put_preferences(
    payload: NotificationPreferencesUpdate,
    service: ServiceDep,
    principal: PrincipalDep,
) -> list[NotificationPreferenceOut]:
    """Eigene Schalter setzen (Bulk; nur Abweichungen werden gespeichert)."""
    prefs = await service.set_preferences(
        principal.sub, [(p.kind, p.enabled) for p in payload.preferences]
    )
    return [NotificationPreferenceOut(kind=k, enabled=e) for k, e in prefs]
