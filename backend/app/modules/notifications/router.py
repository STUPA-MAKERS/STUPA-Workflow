"""Notifications-API-Router (#4-2/#task-reminder, api.md »notifications«).

* ``GET /api/notifications/preferences`` — eigene Benachrichtigungs-Schalter
  (voller Katalog, Default aktiviert).
* ``PUT /api/notifications/preferences`` — Bulk-Update der eigenen Schalter.
* ``GET/PUT /api/admin/notification-settings`` — Plattform-Config
  (Aufgaben-Erinnerungen), P(``admin.notifications``).

Die Preferences-Endpunkte verlangen nur einen eingeloggten Principal (keine
besondere Permission): jede:r verwaltet ausschließlich die eigenen Einstellungen.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.deps import DbSession, Principal, require_principal
from app.modules.notifications.models import NotificationSettings
from app.modules.notifications.schemas import (
    NotificationPreferenceOut,
    NotificationPreferencesUpdate,
    NotificationSettingsOut,
    NotificationSettingsUpdate,
)
from app.modules.notifications.service import NotificationService
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/notifications", tags=["notifications"])
admin_router = APIRouter(prefix="/admin/notification-settings", tags=["notifications"])

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


NotifAdmin = Annotated[Principal, Depends(require_principal("admin.notifications"))]


def _settings_out(row: NotificationSettings) -> NotificationSettingsOut:
    return NotificationSettingsOut(
        taskReminderEnabled=row.task_reminder_enabled,
        taskReminderAfterDays=row.task_reminder_after_days,
        taskReminderRepeatDays=row.task_reminder_repeat_days,
    )


@admin_router.get(
    "", response_model=NotificationSettingsOut, responses=_AUTH_ERRORS
)
async def get_notification_settings(
    service: ServiceDep, _principal: NotifAdmin
) -> NotificationSettingsOut:
    """Plattform-Config lesen (Aufgaben-Erinnerungen, #task-reminder)."""
    return _settings_out(await service.get_notification_settings())


@admin_router.put(
    "",
    response_model=NotificationSettingsOut,
    responses={**_AUTH_ERRORS, 422: _PROBLEM},
)
async def put_notification_settings(
    payload: NotificationSettingsUpdate,
    service: ServiceDep,
    principal: NotifAdmin,
) -> NotificationSettingsOut:
    """Plattform-Config setzen (Teil-Update, auditiert als CONFIG_CHANGE)."""
    row = await service.update_notification_settings(
        actor=principal.sub,
        task_reminder_enabled=payload.task_reminder_enabled,
        task_reminder_after_days=payload.task_reminder_after_days,
        task_reminder_repeat_days=payload.task_reminder_repeat_days,
    )
    return _settings_out(row)
