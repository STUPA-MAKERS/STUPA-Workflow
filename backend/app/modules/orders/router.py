"""Routes of the Bestellungen (F/finance/orders/002872).

- ``GET /applications/{id}/orders`` lists the Bestellungen of an Antrag for everybody who
  reads the Antrag. An applicant and an observer get the short view
  (F/finance/orders/002864).
- ``POST /applications/{id}/orders``, ``PATCH /orders/{id}``, ``POST /orders/{id}/status``
  and ``DELETE /orders/{id}`` need ``order.manage`` and the read of the Antrag.
- A Bestellung of an Antrag that the caller does not read answers 404
  (F/finance/orders/002863), so the answer does not tell that the Bestellung exists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response, status

from app.deps import (
    DbSession,
    SettingsDep,
    get_current_applicant,
    get_current_principal,
    require_principal,
)
from app.modules.applications.access import Access, require_app_view, resolve_app_read
from app.modules.auth.principal import Applicant, Principal
from app.modules.orders.models import PurchaseOrder
from app.modules.orders.numbers import format_number
from app.modules.orders.rules import orders_sum, over_by
from app.modules.orders.schemas import (
    OrderApplicantOut,
    OrderCreate,
    OrderOut,
    OrdersOut,
    OrderStatusIn,
    OrderUpdate,
)
from app.modules.orders.service import MANAGE_PERMISSION, OrderService
from app.shared.errors import ForbiddenError, NotFoundError

router = APIRouter(tags=["orders"])

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"description": "problem+json"} for code in (401, 403, 404, 409, 422)
}

ManagerDep = Annotated[Principal, Depends(require_principal(MANAGE_PERMISSION))]


def get_order_service(db: DbSession, settings: SettingsDep) -> OrderService:
    """Build the service with the current day in the local time zone."""
    return OrderService(db, today=datetime.now(ZoneInfo(settings.local_timezone)).date())


ServiceDep = Annotated[OrderService, Depends(get_order_service)]


def _out(row: PurchaseOrder, positions: tuple[str, ...]) -> OrderOut:
    """Build the member view of a Bestellung."""
    return OrderOut(
        id=row.id,
        number=format_number(row.number),
        applicationId=row.application_id,
        title=row.title,
        kind=row.kind,  # pyright: ignore[reportArgumentType]
        status=row.status,  # pyright: ignore[reportArgumentType]
        supplier=row.supplier,
        url=row.url,
        orderNumber=row.order_number,
        positionIds=positions,
        plannedAmount=row.planned_amount,
        actualAmount=row.actual_amount,
        orderedOn=row.ordered_on,
        deliveredOn=row.delivered_on,
        buyerId=row.buyer_id,
        buyerName=row.buyer_name,
        note=row.note,
        version=row.version,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


def _applicant_out(row: PurchaseOrder) -> OrderApplicantOut:
    """Build the applicant view of a Bestellung: no price, no link and no note."""
    return OrderApplicantOut(
        id=row.id,
        number=format_number(row.number),
        title=row.title,
        kind=row.kind,  # pyright: ignore[reportArgumentType]
        status=row.status,  # pyright: ignore[reportArgumentType]
        orderedOn=row.ordered_on,
        deliveredOn=row.delivered_on,
    )


async def _view(service: OrderService, row: PurchaseOrder) -> OrderOut:
    """Build the member view of one Bestellung with its positions."""
    return _out(row, (await service.positions_of([row.id]))[row.id])


async def _readable(
    db: DbSession,
    service: OrderService,
    order_id: UUID,
    principal: Principal | None,
    applicant: Applicant | None,
    *,
    observers: bool,
) -> tuple[PurchaseOrder, Access]:
    """Return the Bestellung and the access of the caller to its Antrag.

    Raises:
        NotFoundError: No Bestellung has this id, or the caller does not read its Antrag.
        UnauthorizedError: The request carries no identity.
    """
    row = await service.get(order_id)
    try:
        access = await resolve_app_read(
            db, row.application_id, principal, applicant, observers=observers
        )
    except ForbiddenError as exc:
        raise NotFoundError("Bestellung not found.") from exc
    return row, access


@router.get(
    "/applications/{application_id}/orders",
    response_model=OrdersOut,
    responses=_ERRORS,
)
async def list_orders(
    service: ServiceDep, access: Annotated[Access, Depends(require_app_view)]
) -> OrdersOut:
    """List the Bestellungen of an Antrag, the oldest first, with their sum."""
    rows = await service.list_for(access.application_id)
    if access.is_applicant_view:
        return OrdersOut(items=tuple(_applicant_out(row) for row in rows))
    positions = await service.positions_of([row.id for row in rows])
    total = orders_sum((row.status, row.actual_amount, row.planned_amount) for row in rows)
    approved = await service.approved_amount(access.application_id)
    manages = access.principal is not None and access.principal.has(MANAGE_PERMISSION)
    return OrdersOut(
        items=tuple(_out(row, positions[row.id]) for row in rows),
        total=total,
        approvedAmount=approved,
        overBy=over_by(total, approved),
        canManage=manages,
        canCreate=manages and await service.creatable(access.application_id),
    )


@router.post(
    "/applications/{application_id}/orders",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_order(
    application_id: UUID,
    payload: OrderCreate,
    db: DbSession,
    service: ServiceDep,
    principal: ManagerDep,
) -> OrderOut:
    """Create a Bestellung for an approved Antrag of a type with money.

    409 ``application_not_approved``, 422 ``application_type_without_budget``, 422
    ``order_url_invalid``, 422 ``order_buyer_required``, 422 ``order_position_unknown``
    and 409 ``order_position_taken`` refuse the create.
    """
    await resolve_app_read(db, application_id, principal, None)
    row = await service.create(application_id, payload, actor=principal.sub)
    out = await _view(service, row)
    await db.commit()
    return out


@router.get(
    "/orders/{order_id}",
    response_model=OrderOut | OrderApplicantOut,
    responses=_ERRORS,
)
async def get_order(
    order_id: UUID,
    db: DbSession,
    service: ServiceDep,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> OrderOut | OrderApplicantOut:
    """Return one Bestellung; an applicant and an observer get the short view."""
    row, access = await _readable(db, service, order_id, principal, applicant, observers=True)
    return _applicant_out(row) if access.is_applicant_view else await _view(service, row)


@router.patch("/orders/{order_id}", response_model=OrderOut, responses=_ERRORS)
async def patch_order(
    order_id: UUID,
    payload: OrderUpdate,
    db: DbSession,
    service: ServiceDep,
    principal: ManagerDep,
) -> OrderOut:
    """Change the fields that the body names; 409 ``order_version_conflict`` on an old version."""
    await _readable(db, service, order_id, principal, None, observers=False)
    row = await service.update(order_id, payload, actor=principal.sub)
    out = await _view(service, row)
    await db.commit()
    return out


@router.post("/orders/{order_id}/status", response_model=OrderOut, responses=_ERRORS)
async def post_order_status(
    order_id: UUID,
    payload: OrderStatusIn,
    db: DbSession,
    service: ServiceDep,
    principal: ManagerDep,
) -> OrderOut:
    """Set the status; "Bestellt" and "Geliefert" set their empty date to the current day."""
    await _readable(db, service, order_id, principal, None, observers=False)
    row = await service.set_status(order_id, payload.status, payload.version, actor=principal.sub)
    out = await _view(service, row)
    await db.commit()
    return out


@router.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS)
async def delete_order(
    order_id: UUID, db: DbSession, service: ServiceDep, principal: ManagerDep
) -> Response:
    """Delete a Bestellung."""
    await _readable(db, service, order_id, principal, None, observers=False)
    await service.delete(order_id, actor=principal.sub)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
