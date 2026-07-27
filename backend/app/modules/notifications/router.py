"""Notifications API router.

* ``GET /api/notifications/preferences`` — own notification switches (full catalogue, default on).
* ``PUT /api/notifications/preferences`` — bulk update of own switches.
* ``GET/PUT /api/admin/notification-settings`` — platform config, P(``admin.notifications``).

The preferences endpoints need a logged-in principal only. Each user manages the own
settings only.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import DbSession, Principal, require_principal
from app.modules.notifications.models import NotificationSettings
from app.modules.notifications.schemas import (
    MailPreviewOut,
    MailPreviewPayloadRequest,
    MailPreviewRequest,
    MailTemplateCreate,
    MailTemplateOut,
    MailTemplateUpdate,
    MailTemplateUpsert,
    NotificationPreferenceOut,
    NotificationPreferencesUpdate,
    NotificationSettingsOut,
    NotificationSettingsUpdate,
)
from app.modules.notifications.service import NotificationService
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/notifications", tags=["notifications"])
admin_router = APIRouter(prefix="/admin/notification-settings", tags=["notifications"])
templates_router = APIRouter(prefix="/admin/mail-templates", tags=["notifications"])

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
    """Read the own notification switches.

    The response holds the full catalogue. A kind without an entry is enabled.
    """
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
    """Set the own notification switches in bulk.

    The service stores only the switches that differ from the default.
    """
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
    """Read the platform config (task reminders)."""
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
    """Set the platform config (partial update, audited as CONFIG_CHANGE)."""
    row = await service.update_notification_settings(
        actor=principal.sub,
        task_reminder_enabled=payload.task_reminder_enabled,
        task_reminder_after_days=payload.task_reminder_after_days,
        task_reminder_repeat_days=payload.task_reminder_repeat_days,
    )
    return _settings_out(row)


@templates_router.get("", response_model=list[MailTemplateOut], responses=_AUTH_ERRORS)
async def list_mail_templates(
    service: ServiceDep, _principal: NotifAdmin
) -> list[MailTemplateOut]:
    """List all mail templates (i18n subject, body and HTML plus placeholders)."""
    return await service.list_templates()


@templates_router.post(
    "",
    response_model=MailTemplateOut,
    status_code=201,
    responses={**_AUTH_ERRORS, 409: _PROBLEM, 422: _PROBLEM},
)
async def create_mail_template(
    payload: MailTemplateCreate, service: ServiceDep, _principal: NotifAdmin
) -> MailTemplateOut:
    return await service.create_template(payload)


@templates_router.patch(
    "/{template_id}",
    response_model=MailTemplateOut,
    responses={**_AUTH_ERRORS, 404: _PROBLEM, 422: _PROBLEM},
)
async def update_mail_template(
    template_id: UUID,
    payload: MailTemplateUpdate,
    service: ServiceDep,
    _principal: NotifAdmin,
) -> MailTemplateOut:
    return await service.update_template(template_id, payload)


@templates_router.put(
    "",
    response_model=MailTemplateOut,
    responses={**_AUTH_ERRORS, 422: _PROBLEM},
)
async def upsert_mail_template(
    payload: MailTemplateUpsert, service: ServiceDep, _principal: NotifAdmin
) -> MailTemplateOut:
    """Create or update an override by key, including a builtin key."""
    return await service.upsert_template(payload)


@templates_router.delete(
    "/by-key/{key}",
    response_model=MailTemplateOut,
    responses={**_AUTH_ERRORS, 404: _PROBLEM},
)
async def reset_mail_template(
    key: str, service: ServiceDep, _principal: NotifAdmin
) -> MailTemplateOut:
    """Delete the override and restore the builtin default."""
    return await service.reset_template(key)


@templates_router.post(
    "/preview",
    response_model=MailPreviewOut,
    responses={**_AUTH_ERRORS, 422: _PROBLEM},
)
async def preview_mail_payload(
    payload: MailPreviewPayloadRequest, service: ServiceDep, _principal: NotifAdmin
) -> MailPreviewOut:
    """Render an editor draft (no persisted id)."""
    return await service.preview_payload(payload)


@templates_router.post(
    "/{template_id}/preview",
    response_model=MailPreviewOut,
    responses={**_AUTH_ERRORS, 404: _PROBLEM, 422: _PROBLEM},
)
async def preview_mail_template(
    template_id: UUID,
    payload: MailPreviewRequest,
    service: ServiceDep,
    _principal: NotifAdmin,
) -> MailPreviewOut:
    """Render a template with sample context and language (preview)."""
    return await service.preview_template(template_id, payload)
