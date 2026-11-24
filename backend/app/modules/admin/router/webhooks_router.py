"""Admin routes of the outgoing webhooks."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.deps import DbSession
from app.modules.admin.router.deps import (
    _WEBHOOK,
    _WEBHOOK_OR_FLOW,
    ServiceDep,
    WebhookAdmin,
    _errors,
)
from app.modules.admin.schemas import (
    WebhookCatalogEvent,
    WebhookCreate,
    WebhookDeliveryStatusOut,
    WebhookOut,
    WebhookTestOut,
    WebhookUpdate,
)
from app.modules.admin.service.webhooks import catalog_out

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/webhooks",
    response_model=list[WebhookOut],
    dependencies=[_WEBHOOK_OR_FLOW],
    responses=_errors(401, 403),
)
async def list_webhooks(service: ServiceDep) -> list[WebhookOut]:
    """List the webhooks."""
    return await service.list_webhooks()


@router.post(
    "/webhooks",
    response_model=WebhookOut,
    status_code=201,
    responses=_errors(400, 401, 403, 422),
)
async def create_webhook(
    payload: WebhookCreate, service: ServiceDep, principal: WebhookAdmin
) -> WebhookOut:
    """Create a webhook."""
    return await service.create_webhook(payload, principal.sub)


@router.patch(
    "/webhooks/{webhook_id}",
    response_model=WebhookOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_webhook(
    webhook_id: UUID,
    payload: WebhookUpdate,
    service: ServiceDep,
    principal: WebhookAdmin,
) -> WebhookOut:
    """Update a webhook."""
    return await service.update_webhook(webhook_id, payload, principal.sub)


@router.delete(
    "/webhooks/{webhook_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_webhook(webhook_id: UUID, service: ServiceDep, principal: WebhookAdmin) -> None:
    """Delete a webhook and its delivery history.

    The delete cascades to ``webhook_delivery``, so there is no 409 guard. The
    audit log records the removal as ``webhook_config``.
    """
    await service.delete_webhook(webhook_id, principal.sub)


@router.get(
    "/webhooks/catalog",
    response_model=list[WebhookCatalogEvent],
    dependencies=[_WEBHOOK],
    responses=_errors(401, 403),
)
async def webhook_catalog() -> list[WebhookCatalogEvent]:
    """Return the event catalog with the fields of each event and their example values.

    The dialog builds the event and field choice and the payload preview from it
    (§F/integrations/webhooks/002411, 002415).
    """
    return catalog_out()


@router.post(
    "/webhooks/{webhook_id}/test",
    response_model=WebhookTestOut,
    status_code=202,
    responses=_errors(401, 403, 404, 409),
)
async def send_webhook_test(
    webhook_id: UUID, session: DbSession, service: ServiceDep, _principal: WebhookAdmin
) -> WebhookTestOut:
    """Queue a test delivery with example values (§F/integrations/webhooks/002416)."""
    result = await service.send_test_delivery(webhook_id)
    await session.commit()
    return result


@router.get(
    "/webhooks/delivery-status",
    response_model=list[WebhookDeliveryStatusOut],
    dependencies=[_WEBHOOK],
    responses=_errors(401, 403),
)
async def list_webhook_delivery_status(
    service: ServiceDep,
) -> list[WebhookDeliveryStatusOut]:
    """Return the latest delivery state per webhook.

    The response holds a coarse state (``sent``, ``pending``, ``dead`` or
    ``never``) and a coarse failure class. An operator can diagnose a mistyped
    or internal webhook with it. The response leaks no resolved internal IP and
    no response body.
    """
    return await service.list_webhook_delivery_status()
