"""Notifications-Admin-Router (T-18, api.md §6).

Endpunkte (alle Permission ``notification.manage``):

* ``GET/POST  /api/admin/notification-rules``        — Regeln listen/anlegen.
* ``PATCH     /api/admin/notification-rules/{id}``   — Regel ändern (z. B. aus/an).
* ``GET/POST  /api/admin/mail-templates``            — Templates listen/anlegen.
* ``PATCH     /api/admin/mail-templates/{id}``       — Template ändern.
* ``POST      /api/admin/mail-templates/{id}/preview`` — Vorschau rendern.

Fehler-Antworten werden als ``ProblemDetail`` deklariert (problem+json-Contract).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import DbSession, require_principal
from app.modules.notifications.schemas import (
    MailPreviewOut,
    MailPreviewRequest,
    MailTemplateCreate,
    MailTemplateOut,
    MailTemplateUpdate,
    NotificationRuleCreate,
    NotificationRuleOut,
    NotificationRuleUpdate,
)
from app.modules.notifications.service import NotificationService
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/admin", tags=["notifications"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}

_MANAGE = Depends(require_principal("notification.manage"))


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_notifications_service(session: DbSession) -> NotificationService:
    return NotificationService(session)


ServiceDep = Annotated[NotificationService, Depends(get_notifications_service)]


# --------------------------------------------------------------------------- #
# Notification-Rules
# --------------------------------------------------------------------------- #
@router.get(
    "/notification-rules",
    response_model=list[NotificationRuleOut],
    dependencies=[_MANAGE],
    responses=_errors(401, 403),
)
async def list_notification_rules(service: ServiceDep) -> list[NotificationRuleOut]:
    return await service.list_rules()


@router.post(
    "/notification-rules",
    response_model=NotificationRuleOut,
    status_code=201,
    dependencies=[_MANAGE],
    # 400 = malformed JSON body (Parse-Fehler), 422 = Schema-Validierung.
    responses=_errors(400, 401, 403, 422),
)
async def create_notification_rule(
    payload: NotificationRuleCreate, service: ServiceDep
) -> NotificationRuleOut:
    return await service.create_rule(payload)


@router.patch(
    "/notification-rules/{rule_id}",
    response_model=NotificationRuleOut,
    dependencies=[_MANAGE],
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_notification_rule(
    rule_id: UUID, payload: NotificationRuleUpdate, service: ServiceDep
) -> NotificationRuleOut:
    return await service.update_rule(rule_id, payload)


# --------------------------------------------------------------------------- #
# Mail-Templates
# --------------------------------------------------------------------------- #
@router.get(
    "/mail-templates",
    response_model=list[MailTemplateOut],
    dependencies=[_MANAGE],
    responses=_errors(401, 403),
)
async def list_mail_templates(service: ServiceDep) -> list[MailTemplateOut]:
    return await service.list_templates()


@router.post(
    "/mail-templates",
    response_model=MailTemplateOut,
    status_code=201,
    dependencies=[_MANAGE],
    responses=_errors(400, 401, 403, 409, 422),
)
async def create_mail_template(
    payload: MailTemplateCreate, service: ServiceDep
) -> MailTemplateOut:
    return await service.create_template(payload)


@router.patch(
    "/mail-templates/{template_id}",
    response_model=MailTemplateOut,
    dependencies=[_MANAGE],
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_mail_template(
    template_id: UUID, payload: MailTemplateUpdate, service: ServiceDep
) -> MailTemplateOut:
    return await service.update_template(template_id, payload)


@router.post(
    "/mail-templates/{template_id}/preview",
    response_model=MailPreviewOut,
    dependencies=[_MANAGE],
    responses=_errors(400, 401, 403, 404, 422),
)
async def preview_mail_template(
    template_id: UUID, payload: MailPreviewRequest, service: ServiceDep
) -> MailPreviewOut:
    return await service.preview_template(template_id, payload)
